"""
비밀번호 관리 모듈
"""
import re
from typing import Tuple
from passlib.context import CryptContext
from fastapi import HTTPException, status

class PasswordManager:
    """비밀번호 암호화, 검증, 정책 관리를 담당하는 클래스"""
    
    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.min_length = 8
        self.require_uppercase = True
        self.require_lowercase = True
        self.require_numbers = True
        self.require_special_chars = True
    
    def hash_password(self, password: str) -> str:
        """비밀번호 해싱"""
        return self.pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """비밀번호 검증"""
        return self.pwd_context.verify(plain_password, hashed_password)
    
    def validate_password_policy(self, password: str) -> Tuple[bool, list]:
        """비밀번호 정책 검증"""
        errors = []
        
        # 길이 검증
        if len(password) < self.min_length:
            errors.append(f"Password must be at least {self.min_length} characters long")
        
        # 대문자 검증
        if self.require_uppercase and not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter")
        
        # 소문자 검증
        if self.require_lowercase and not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter")
        
        # 숫자 검증
        if self.require_numbers and not re.search(r'\d', password):
            errors.append("Password must contain at least one number")
        
        # 특수문자 검증
        if self.require_special_chars and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("Password must contain at least one special character")
        
        return len(errors) == 0, errors
    
    def check_password_strength(self, password: str) -> str:
        """비밀번호 강도 평가"""
        score = 0
        
        # 길이 점수
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        
        # 문자 종류 점수
        if re.search(r'[a-z]', password):
            score += 1
        if re.search(r'[A-Z]', password):
            score += 1
        if re.search(r'\d', password):
            score += 1
        if re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            score += 1
        
        # 강도 평가
        if score <= 2:
            return "weak"
        elif score <= 4:
            return "medium"
        else:
            return "strong"
    
    def generate_secure_password(self, length: int = 12) -> str:
        """보안 비밀번호 생성"""
        import secrets
        import string
        
        # 문자 세트 정의
        lowercase = string.ascii_lowercase
        uppercase = string.ascii_uppercase
        digits = string.digits
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        
        # 각 카테고리에서 최소 1개씩 선택
        password = [
            secrets.choice(lowercase),
            secrets.choice(uppercase),
            secrets.choice(digits),
            secrets.choice(special_chars)
        ]
        
        # 나머지 길이만큼 랜덤 선택
        all_chars = lowercase + uppercase + digits + special_chars
        for _ in range(length - 4):
            password.append(secrets.choice(all_chars))
        
        # 비밀번호 섞기
        secrets.SystemRandom().shuffle(password)
        
        return ''.join(password)
