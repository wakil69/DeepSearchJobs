import { z } from "zod";

export const getEditCompanySchema = (t: (key: string) => string) =>
  z.object({
    id: z.number(),
    name: z
      .string()
      .min(2, t("validation.nameTooShort"))
      .max(100, t("validation.nameTooLong")),
    website: z.url(t("validation.invalidUrl")).or(z.literal("")).optional(),

    internalJobListingPages: z
      .array(z.object({ value: z.url(t("validation.invalidUrl")) }))
      .default([]),

    externalJobListingPages: z
      .array(z.object({ value: z.url(t("validation.invalidUrl")) }))
      .default([]),

    emails: z
      .array(z.object({ value: z.email(t("validation.invalidEmail")) }))
      .default([]),
  });

export type EditCompanyForm = z.infer<ReturnType<typeof getEditCompanySchema>>;
