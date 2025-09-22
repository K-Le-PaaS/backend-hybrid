"""
다중 인증(MFA) 모듈
"""
import pyotp
import qrcode
import io
import base64
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from app.core.config import settings

class MFAManager:
    """다중 인증을 담당하는 클래스"""
    
    def __init__(self):
        self.issuer_name = "K-Le-PaaS"
        self.algorithm = "sha1"
        self.digits = 6
        self.period = 30
    
    def generate_secret(self, user_id: str) -> str:
        """TOTP 시크릿 생성"""
        return pyotp.random_base32()
    
    def generate_qr_code(self, user_id: str, email: str, secret: str) -> str:
        """QR 코드 생성 (Base64 인코딩)"""
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=email,
            issuer_name=self.issuer_name
        )
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 이미지를 Base64로 인코딩
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    
    def verify_totp(self, secret: str, token: str) -> bool:
        """TOTP 토큰 검증"""
        try:
            totp = pyotp.TOTP(secret)
            return totp.verify(token, valid_window=1)  # 1분 윈도우 허용
        except Exception:
            return False
    
    def generate_backup_codes(self, count: int = 10) -> list:
        """백업 코드 생성"""
        import secrets
        import string
        
        codes = []
        for _ in range(count):
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            codes.append(code)
        
        return codes
    
    def verify_backup_code(self, user_backup_codes: list, code: str) -> bool:
        """백업 코드 검증"""
        if code in user_backup_codes:
            # 사용된 백업 코드 제거
            user_backup_codes.remove(code)
            return True
        return False
    
    def generate_sms_code(self) -> str:
        """SMS 인증 코드 생성"""
        import secrets
        return str(secrets.randbelow(900000) + 100000)  # 6자리 숫자
    
    def verify_sms_code(self, stored_code: str, provided_code: str) -> bool:
        """SMS 인증 코드 검증"""
        return stored_code == provided_code
    
    def is_mfa_enabled(self, user_mfa_settings: Dict[str, Any]) -> bool:
        """MFA 활성화 여부 확인"""
        return user_mfa_settings.get("enabled", False)
    
    def get_mfa_methods(self, user_mfa_settings: Dict[str, Any]) -> list:
        """사용자의 MFA 방법 목록 반환"""
        methods = []
        
        if user_mfa_settings.get("totp_enabled", False):
            methods.append("totp")
        
        if user_mfa_settings.get("sms_enabled", False):
            methods.append("sms")
        
        if user_mfa_settings.get("backup_codes_enabled", False):
            methods.append("backup_codes")
        
        return methods
    
    def validate_mfa_setup(self, user_mfa_settings: Dict[str, Any]) -> Dict[str, Any]:
        """MFA 설정 검증"""
        errors = []
        warnings = []
        
        # 최소 하나의 MFA 방법이 활성화되어야 함
        methods = self.get_mfa_methods(user_mfa_settings)
        if not methods:
            errors.append("At least one MFA method must be enabled")
        
        # TOTP 설정 검증
        if user_mfa_settings.get("totp_enabled", False):
            if not user_mfa_settings.get("totp_secret"):
                errors.append("TOTP secret is required when TOTP is enabled")
        
        # SMS 설정 검증
        if user_mfa_settings.get("sms_enabled", False):
            if not user_mfa_settings.get("sms_phone"):
                errors.append("SMS phone number is required when SMS is enabled")
        
        # 백업 코드 검증
        if user_mfa_settings.get("backup_codes_enabled", False):
            backup_codes = user_mfa_settings.get("backup_codes", [])
            if len(backup_codes) < 5:
                warnings.append("Consider generating more backup codes")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
