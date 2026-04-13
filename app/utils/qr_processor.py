import cv2
import numpy as np
from pyzbar.pyzbar import decode
from urllib.parse import urlparse, parse_qs

class QRProcessor:
    @staticmethod
    def extract_upi_details(image_path: str):
        # Read the image
        img = cv2.imread(image_path)
        # Decode QR codes
        decoded_objects = decode(img)
        
        for obj in decoded_objects:
            data = obj.data.decode("utf-8")
            if data.startswith("upi://pay"):
                # Parse UPI URI: upi://pay?pa=name@bank&pn=PayeeName&am=100
                parsed = urlparse(data)
                params = parse_qs(parsed.query)
                
                return {
                    "upi_id": params.get("pa", [None])[0],
                    "payee_name": params.get("pn", [None])[0],
                    "amount": params.get("am", [None])[0],
                    "raw_data": data
                }
        return None