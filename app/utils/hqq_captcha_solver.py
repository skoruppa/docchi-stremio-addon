import base64
import io
import cv2
import numpy as np
from PIL import Image


def solve_hqq_captcha(image_base64: str) -> tuple[int, int]:
    """Detect play button circle in HQQ captcha image."""
    if "base64," in image_base64:
        image_base64 = image_base64.split("base64,")[1]

    img_data = base64.b64decode(image_base64)
    img = cv2.cvtColor(np.array(Image.open(io.BytesIO(img_data))), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 2)

    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=50,
        param1=100,
        param2=25,
        minRadius=15,
        maxRadius=80
    )

    if circles is not None and len(circles[0]) > 0:
        circles = np.uint16(np.around(circles))
        center_x, center_y, radius = circles[0][0]
    else:
        h, w = img.shape[:2]
        center_x, center_y, radius = w // 2, h // 2, 0

    return add_random_offset(center_x, center_y, radius)


def add_random_offset(x: int, y: int, radius: int) -> tuple[int, int]:
    """Add small random offset to avoid clicking exact center."""
    import random
    x, y, radius = int(x), int(y), int(radius)
    offset = max(1, radius // 3)
    new_x = max(0, x + random.randint(-offset, offset))
    new_y = max(0, y + random.randint(-offset, offset))
    return new_x, new_y