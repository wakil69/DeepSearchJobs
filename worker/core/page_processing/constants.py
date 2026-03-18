import re 

USELESS_TAGS = [
    "script",
    "noscript",
    "template",
    "canvas",
    "style",
    "link",
    "meta",
    "iframe",
    "object",
    "embed",
    "picture",
    "video",
    "audio",
    "track",
]

JSON_HEAVY_PATTERN = re.compile(
    r'^\s*[\[{].*[\]}]\s*$', 
    re.DOTALL
)