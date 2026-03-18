import os
import re
import io
import base64
import random
import aiofiles
import aiofiles.os
import aioboto3
import aiohttp

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Page
from typing import Optional
from worker.dependencies import (
    CLOUDFLARE_R2_BUCKET,
    CLOUDFLARE_R2_ENDPOINT,
    CLOUDFLARE_R2_ACCESS_KEY,
    CLOUDFLARE_R2_SECRET_KEY,
)


class FindCompanyLogo:
    def __init__(
        self,
        session_logger,
        company_name: str,
        company_id: int,
        timeout=20000,
    ):
        self.company_name = company_name
        self.company_id = company_id
        self.session_logger = session_logger
        self.timeout = timeout

    async def handle_google_consent(self, page) -> None:
        """Detect and click the 'Reject all' button if the Google consent popup appears."""
        try:
            locator = page.locator("//button[contains(., 'Reject all')]").first
            await locator.wait_for(timeout=5000)
            await locator.click()
            self.session_logger.info("Google Consent Popup: 'Reject all' clicked.")
        except PlaywrightTimeoutError:
            self.session_logger.info("No Google Consent Popup detected.")
        except Exception as e:
            self.session_logger.warning(f"Error handling Google consent popup: {e}")

    async def get_company_logo_url(self, page: Page) -> Optional[str]:
        """
        Search for a company's logo on Google Images, download it, and upload to Cloudflare R2 (or other service...).
        """
        search_query = f"{self.company_name} logo png"
        google_images_url = (
            "https://www.google.com/search?tbm=isch&q=" + search_query.replace(" ", "+")
        )

        try:
            os.makedirs("./tmp", exist_ok=True)

            # Go to Google Images
            await page.goto(
                google_images_url, timeout=self.timeout, wait_until="load"
            )

            await page.wait_for_timeout(random.uniform(1000, 3000))

            # Handle Google consent pop-up if it appears
            await self.handle_google_consent(page)

            # Wait for at least one image result to load
            locator = page.locator("//div[contains(@class,'mNsIhb')]//img").first
            await locator.wait_for(timeout=10000)

            # Get the first image source
            logo_url = await locator.first.get_attribute("src")

            if not logo_url:
                self.session_logger.warning(f"No image source found for {self.company_name}.")
                return None

            # If it's a base64 image
            if logo_url.startswith("data:image"):
                self.session_logger.warning(
                    f"The logo is a base64-encoded image for {self.company_name}. Decoding..."
                )
                temp_path = await self.save_base64_image(logo_url)
            else:
                self.session_logger.info(f"Found logo URL for {self.company_name}: {logo_url}")
                temp_path = await self.download_image(logo_url)

            # Upload to Cloudflare R2
            if temp_path:
                cloudflare_url = await self.upload_to_cloudflare(temp_path)
                return cloudflare_url

        except PlaywrightTimeoutError:
            self.session_logger.error(
                f"Timeout while searching for {self.company_name}'s logo."
            )
        except Exception as e:
            self.session_logger.error(
                f"An error occurred while fetching the logo for {self.company_name}: {e}"
            )

        return None

    async def save_base64_image(self, base64_data: str) -> Optional[str]:
        """
        Extracts and saves a base64 image as a file.
        """
        try:
            match = re.match(
                r"data:image/(?P<ext>png|jpg|jpeg);base64,(?P<data>.+)", base64_data
            )
            if not match:
                self.session_logger.error("Invalid base64 image format.")
                return None

            image_extension = match.group("ext")
            image_data = base64.b64decode(match.group("data"))

            filename = f"{self.company_name.replace(' ', '_')}.{image_extension}"
            temp_path = f"./tmp/{filename}"

            async with aiofiles.open(temp_path, "wb") as file:
                await file.write(image_data)

            self.session_logger.info(f"Base64 image saved as {temp_path}")
            return temp_path

        except Exception as e:
            self.session_logger.error(f"Error decoding base64 image: {e}")
            return None

    async def download_image(self, image_url: str) -> Optional[str]:
        """
        Downloads an image from a URL and saves it as a file.
        """
        try:
            filename = f"{self.company_name.replace(' ', '_')}.png"
            temp_path = f"./tmp/{filename}"

            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    response.raise_for_status()
                    async with aiofiles.open(temp_path, "wb") as file:
                        async for chunk in response.content.iter_chunked(1024):
                            await file.write(chunk)

            self.session_logger.info(f"Image downloaded: {temp_path}")
            return temp_path

        except Exception as e:
            self.session_logger.error(f"Error downloading image: {e}")
            return None

    async def upload_to_cloudflare(self, file_path: str) -> Optional[str]:
        """
        Uploads the image to Cloudflare R2 and returns the public URL.
        """
        try:
            _, file_extension = os.path.splitext(file_path)
            object_key = f"companies/{self.company_id}/logo/logo{file_extension}"

            async with aiofiles.open(file_path, "rb") as file:
                file_content = await file.read()

            async with aioboto3.Session().client(
                "s3",
                endpoint_url=CLOUDFLARE_R2_ENDPOINT,
                aws_access_key_id=CLOUDFLARE_R2_ACCESS_KEY,
                aws_secret_access_key=CLOUDFLARE_R2_SECRET_KEY,
            ) as s3:
                await s3.upload_fileobj(
                    io.BytesIO(file_content), CLOUDFLARE_R2_BUCKET, object_key
                )

            cloudflare_url = (
                f"{CLOUDFLARE_R2_ENDPOINT}/{CLOUDFLARE_R2_BUCKET}/{object_key}"
            )
            self.session_logger.info(f"Uploaded to Cloudflare: {cloudflare_url}")

            await aiofiles.os.remove(file_path)
            return cloudflare_url

        except Exception as e:
            self.session_logger.error(f"Error uploading to Cloudflare: {e}")
            return None
