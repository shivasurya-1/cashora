import cloudinary
import cloudinary.uploader
from app.core.config import settings
from typing import Optional
import uuid
from datetime import datetime

# Configure Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)

class CloudinaryService:
    """Service for handling file uploads to Cloudinary"""
    
    @staticmethod
    def upload_receipt(file_content: bytes, filename: str, expense_id: Optional[str] = None) -> dict:
        """
        Upload a receipt/bill image to Cloudinary
        
        Args:
            file_content: The file content as bytes
            filename: Original filename
            expense_id: Optional expense request ID for organizing files
            
        Returns:
            dict with 'url' and 'public_id'
        """
        try:
            # Generate unique filename
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            public_id = f"{settings.CLOUDINARY_FOLDER}/{expense_id or 'temp'}_{timestamp}_{unique_id}"
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                file_content,
                public_id=public_id,
                folder=settings.CLOUDINARY_FOLDER,
                resource_type="auto",  # Automatically detect file type
                overwrite=False,
                transformation=[
                    {'quality': 'auto:good'},  # Optimize quality
                    {'fetch_format': 'auto'}   # Automatically choose best format
                ]
            )
            
            return {
                "url": result.get("secure_url"),
                "public_id": result.get("public_id"),
                "format": result.get("format"),
                "size": result.get("bytes")
            }
            
        except Exception as e:
            raise Exception(f"Failed to upload file to Cloudinary: {str(e)}")
    
    @staticmethod
    def delete_receipt(public_id: str) -> bool:
        """
        Delete a receipt from Cloudinary
        
        Args:
            public_id: The Cloudinary public_id of the file
            
        Returns:
            bool indicating success
        """
        try:
            result = cloudinary.uploader.destroy(public_id)
            return result.get("result") == "ok"
        except Exception as e:
            print(f"Failed to delete file from Cloudinary: {str(e)}")
            return False
    
    @staticmethod
    def get_receipt_url(public_id: str, transformation: Optional[dict] = None) -> str:
        """
        Get a URL for a receipt with optional transformations
        
        Args:
            public_id: The Cloudinary public_id
            transformation: Optional transformation parameters
            
        Returns:
            str: The URL to access the file
        """
        try:
            if transformation:
                url = cloudinary.CloudinaryImage(public_id).build_url(**transformation)
            else:
                url = cloudinary.CloudinaryImage(public_id).build_url()
            return url
        except Exception as e:
            raise Exception(f"Failed to generate URL: {str(e)}")

# Create singleton instance
cloudinary_service = CloudinaryService()
