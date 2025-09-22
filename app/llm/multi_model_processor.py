#!/usr/bin/env python3
"""
다중 AI 모델 통합 프로세서
Claude, GPT-4, Gemini 등 여러 LLM을 동시에 활용하여 최적의 응답을 제공
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class ModelType(str, Enum):
    """지원하는 AI 모델 타입"""
    CLAUDE = "claude"
    GPT4 = "gpt4"
    GEMINI = "gemini"

class ResponseQuality(str, Enum):
    """응답 품질 등급"""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"

@dataclass
class ModelResponse:
    """AI 모델 응답 데이터 클래스"""
    model_type: ModelType
    content: str
    confidence: float
    processing_time: float
    tokens_used: Optional[int] = None
    error: Optional[str] = None

@dataclass
class ProcessedCommand:
    """처리된 명령 데이터 클래스"""
    original_command: str
    interpreted_command: Dict[str, Any]
    confidence: float
    suggestions: List[str]
    model_responses: List[ModelResponse]
    best_response: ModelResponse
    quality: ResponseQuality

class ModelClient:
    """AI 모델 클라이언트 기본 클래스"""
    
    def __init__(self, model_type: ModelType, base_url: str, api_key: str):
        self.model_type = model_type
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def process_command(self, command: str, context: Dict[str, Any]) -> ModelResponse:
        """명령 처리 (하위 클래스에서 구현)"""
        raise NotImplementedError
    
    async def close(self):
        """클라이언트 종료"""
        await self.client.aclose()

class ClaudeClient(ModelClient):
    """Claude 모델 클라이언트"""
    
    async def process_command(self, command: str, context: Dict[str, Any]) -> ModelResponse:
        """Claude를 통한 명령 처리"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            payload = {
                "model": "claude-3-sonnet-20240229",
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "system",
                        "content": self._build_system_prompt(context)
                    },
                    {
                        "role": "user",
                        "content": command
                    }
                ]
            }
            
            response = await self.client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()
            content = data["content"][0]["text"]
            processing_time = asyncio.get_event_loop().time() - start_time
            
            return ModelResponse(
                model_type=ModelType.CLAUDE,
                content=content,
                confidence=self._calculate_confidence(content),
                processing_time=processing_time,
                tokens_used=data.get("usage", {}).get("total_tokens")
            )
            
        except Exception as e:
            logger.error(f"Claude processing error: {e}")
            return ModelResponse(
                model_type=ModelType.CLAUDE,
                content="",
                confidence=0.0,
                processing_time=asyncio.get_event_loop().time() - start_time,
                error=str(e)
            )
    
    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """시스템 프롬프트 구성"""
        return f"""
        You are an expert Kubernetes DevOps assistant for K-Le-PaaS platform.
        Current project context: {context.get('project_name', 'Unknown')}
        Available deployments: {context.get('deployments', [])}
        
        Parse the user's natural language command and return a JSON response with:
        - action: The main action (deploy, scale, rollback, etc.)
        - target: The target resource (app name, service, etc.)
        - parameters: Additional parameters (replicas, environment, etc.)
        - confidence: Your confidence in the interpretation (0.0-1.0)
        """
    
    def _calculate_confidence(self, content: str) -> float:
        """응답 신뢰도 계산"""
        # 간단한 신뢰도 계산 로직
        if not content or len(content) < 10:
            return 0.1
        if "error" in content.lower() or "unclear" in content.lower():
            return 0.3
        if len(content) > 50 and "json" in content.lower():
            return 0.8
        return 0.6

class GPT4Client(ModelClient):
    """GPT-4 모델 클라이언트"""
    
    async def process_command(self, command: str, context: Dict[str, Any]) -> ModelResponse:
        """GPT-4를 통한 명령 처리"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            payload = {
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": self._build_system_prompt(context)
                    },
                    {
                        "role": "user",
                        "content": command
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.1
            }
            
            response = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            processing_time = asyncio.get_event_loop().time() - start_time
            
            return ModelResponse(
                model_type=ModelType.GPT4,
                content=content,
                confidence=self._calculate_confidence(content),
                processing_time=processing_time,
                tokens_used=data.get("usage", {}).get("total_tokens")
            )
            
        except Exception as e:
            logger.error(f"GPT-4 processing error: {e}")
            return ModelResponse(
                model_type=ModelType.GPT4,
                content="",
                confidence=0.0,
                processing_time=asyncio.get_event_loop().time() - start_time,
                error=str(e)
            )
    
    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """시스템 프롬프트 구성"""
        return f"""
        You are a Kubernetes DevOps expert for K-Le-PaaS platform.
        Project: {context.get('project_name', 'Unknown')}
        Deployments: {context.get('deployments', [])}
        
        Convert natural language to structured Kubernetes commands.
        Return JSON with: action, target, parameters, confidence.
        """
    
    def _calculate_confidence(self, content: str) -> float:
        """응답 신뢰도 계산"""
        if not content or len(content) < 10:
            return 0.1
        if "error" in content.lower() or "cannot" in content.lower():
            return 0.2
        if "json" in content.lower() and len(content) > 30:
            return 0.9
        return 0.7

class GeminiClient(ModelClient):
    """Gemini 모델 클라이언트 (고급 NLP 통합)"""
    
    def __init__(self, model_type: ModelType, base_url: str, api_key: str):
        super().__init__(model_type, base_url, api_key)
        self.advanced_nlp_enabled = True
    
    async def process_command(self, command: str, context: Dict[str, Any]) -> ModelResponse:
        """Gemini를 통한 고급 명령 처리"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # 고급 NLP 기능이 활성화된 경우
            if self.advanced_nlp_enabled:
                return await self._process_advanced_command(command, context, start_time)
            else:
                return await self._process_basic_command(command, context, start_time)
                
        except Exception as e:
            logger.error(f"Gemini processing error: {e}")
            return ModelResponse(
                model_type=ModelType.GEMINI,
                content="",
                confidence=0.0,
                processing_time=asyncio.get_event_loop().time() - start_time,
                error=str(e)
            )
    
    async def _process_advanced_command(self, command: str, context: Dict[str, Any], start_time: float) -> ModelResponse:
        """고급 NLP 기능을 활용한 명령 처리"""
        try:
            # 1. 컨텍스트 인식 분석
            context_analysis = await self._analyze_context(command, context)
            
            # 2. 명령 복잡도 평가
            complexity_score = self._evaluate_complexity(command, context)
            
            # 3. 다단계 프롬프트 구성
            system_prompt = self._build_advanced_system_prompt(context, context_analysis, complexity_score)
            
            # 4. Gemini API 호출
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"{system_prompt}\n\nUser command: {command}"
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "maxOutputTokens": 1500,
                    "temperature": 0.1,
                    "topP": 0.8,
                    "topK": 40
                },
                "safetySettings": [
                    {
                        "category": "HARM_CATEGORY_HARASSMENT",
                        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                    },
                    {
                        "category": "HARM_CATEGORY_HATE_SPEECH",
                        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                    }
                ]
            }
            
            response = await self.client.post(
                f"{self.base_url}/v1beta/models/gemini-pro:generateContent",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            processing_time = asyncio.get_event_loop().time() - start_time
            
            # 5. 고급 신뢰도 계산
            confidence = self._calculate_advanced_confidence(content, context_analysis, complexity_score)
            
            return ModelResponse(
                model_type=ModelType.GEMINI,
                content=content,
                confidence=confidence,
                processing_time=processing_time,
                tokens_used=data.get("usageMetadata", {}).get("totalTokenCount")
            )
            
        except Exception as e:
            logger.error(f"Advanced Gemini processing error: {e}")
            raise
    
    async def _process_basic_command(self, command: str, context: Dict[str, Any], start_time: float) -> ModelResponse:
        """기본 명령 처리 (폴백)"""
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"{self._build_basic_system_prompt(context)}\n\nUser command: {command}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 1000,
                "temperature": 0.1
            }
        }
        
        response = await self.client.post(
            f"{self.base_url}/v1beta/models/gemini-pro:generateContent",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json=payload
        )
        response.raise_for_status()
        
        data = response.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        processing_time = asyncio.get_event_loop().time() - start_time
        
        return ModelResponse(
            model_type=ModelType.GEMINI,
            content=content,
            confidence=self._calculate_basic_confidence(content),
            processing_time=processing_time
        )
    
    async def _analyze_context(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """컨텍스트 분석"""
        analysis = {
            "has_project_context": bool(context.get('project_name')),
            "has_deployment_context": bool(context.get('deployments')),
            "command_length": len(command),
            "contains_technical_terms": any(term in command.lower() for term in [
                'deploy', 'scale', 'rollback', 'kubernetes', 'pod', 'service', 'configmap'
            ]),
            "contains_ambiguity_indicators": any(indicator in command.lower() for indicator in [
                'maybe', 'perhaps', 'might', 'could', 'possibly', '아마', '혹시', '아마도'
            ]),
            "user_experience_level": self._estimate_user_experience(command, context)
        }
        return analysis
    
    def _evaluate_complexity(self, command: str, context: Dict[str, Any]) -> float:
        """명령 복잡도 평가 (0.0-1.0)"""
        complexity = 0.0
        
        # 명령 길이
        if len(command) > 50:
            complexity += 0.2
        elif len(command) > 20:
            complexity += 0.1
        
        # 기술적 용어 사용
        technical_terms = ['kubernetes', 'deployment', 'service', 'configmap', 'secret', 'ingress', 'namespace']
        term_count = sum(1 for term in technical_terms if term in command.lower())
        complexity += min(term_count * 0.1, 0.3)
        
        # 조건부 명령
        if any(word in command.lower() for word in ['if', 'when', 'unless', '만약', '경우', '때']):
            complexity += 0.2
        
        # 다중 액션
        action_words = ['deploy', 'scale', 'update', 'delete', 'create', '배포', '스케일', '업데이트', '삭제', '생성']
        action_count = sum(1 for word in action_words if word in command.lower())
        if action_count > 1:
            complexity += 0.2
        
        return min(complexity, 1.0)
    
    def _estimate_user_experience(self, command: str, context: Dict[str, Any]) -> str:
        """사용자 경험 수준 추정"""
        # 기술적 용어 사용 빈도
        technical_terms = ['kubernetes', 'deployment', 'service', 'pod', 'namespace', 'configmap']
        technical_count = sum(1 for term in technical_terms if term in command.lower())
        
        # 명령의 구체성
        specific_indicators = ['replicas', 'port', 'image', 'env', 'volume', '복제본', '포트', '이미지', '환경변수']
        specific_count = sum(1 for indicator in specific_indicators if indicator in command.lower())
        
        if technical_count >= 3 and specific_count >= 2:
            return "expert"
        elif technical_count >= 1 or specific_count >= 1:
            return "intermediate"
        else:
            return "beginner"
    
    def _build_advanced_system_prompt(self, context: Dict[str, Any], context_analysis: Dict[str, Any], complexity_score: float) -> str:
        """고급 시스템 프롬프트 구성"""
        user_level = context_analysis.get("user_experience_level", "beginner")
        
        base_prompt = f"""
        You are an advanced Kubernetes DevOps assistant for K-Le-PaaS platform.
        
        Project Context:
        - Project: {context.get('project_name', 'Unknown')}
        - Current Deployments: {context.get('deployments', [])}
        - User Level: {user_level}
        - Command Complexity: {complexity_score:.2f}
        
        Advanced Capabilities:
        1. Context-aware interpretation
        2. Ambiguity detection and clarification
        3. Multi-step command decomposition
        4. Intelligent parameter inference
        5. Risk assessment and warnings
        """
        
        if user_level == "beginner":
            base_prompt += """
        
        For beginners, provide:
        - Clear, simple explanations
        - Step-by-step guidance
        - Safety warnings for destructive operations
        - Alternative approaches when possible
        """
        elif user_level == "intermediate":
            base_prompt += """
        
        For intermediate users, provide:
        - Technical details with explanations
        - Best practices and recommendations
        - Potential issues and solutions
        - Optimization suggestions
        """
        else:  # expert
            base_prompt += """
        
        For experts, provide:
        - Concise, technical responses
        - Advanced configuration options
        - Performance considerations
        - Integration possibilities
        """
        
        base_prompt += f"""
        
        Return a comprehensive JSON response with:
        {{
            "action": "primary action (deploy, scale, rollback, etc.)",
            "target": "target resource name",
            "parameters": {{
                "replicas": "number of replicas",
                "environment": "staging/production",
                "image": "container image",
                "ports": "port mappings",
                "env_vars": "environment variables",
                "resources": "resource limits/requests",
                "strategy": "deployment strategy"
            }},
            "confidence": "confidence score (0.0-1.0)",
            "ambiguities": [
                {{
                    "type": "ambiguity type",
                    "description": "what's unclear",
                    "suggestions": ["clarification options"]
                }}
            ],
            "suggestions": [
                {{
                    "type": "improvement type",
                    "text": "suggestion text",
                    "priority": "high/medium/low"
                }}
            ],
            "alternatives": [
                {{
                    "description": "alternative approach",
                    "pros": ["advantages"],
                    "cons": ["disadvantages"]
                }}
            ],
            "warnings": [
                {{
                    "type": "warning type",
                    "message": "warning text",
                    "severity": "high/medium/low"
                }}
            ],
            "next_steps": [
                "suggested follow-up actions"
            ],
            "learning_notes": "key concepts for user improvement"
        }}
        """
        
        return base_prompt
    
    def _build_basic_system_prompt(self, context: Dict[str, Any]) -> str:
        """기본 시스템 프롬프트 구성 (폴백)"""
        return f"""
        You are a Kubernetes DevOps assistant for K-Le-PaaS.
        Project: {context.get('project_name', 'Unknown')}
        Deployments: {context.get('deployments', [])}
        
        Parse natural language and return JSON with action, target, parameters, confidence.
        """
    
    def _calculate_advanced_confidence(self, content: str, context_analysis: Dict[str, Any], complexity_score: float) -> float:
        """고급 신뢰도 계산"""
        base_confidence = 0.5
        
        # 기본 품질 체크
        if not content or len(content) < 20:
            return 0.1
        
        if "error" in content.lower() or "cannot" in content.lower():
            return 0.2
        
        # JSON 구조 확인
        if "{" in content and "}" in content:
            base_confidence += 0.3
        
        # 필수 필드 확인
        required_fields = ["action", "target", "confidence"]
        field_bonus = sum(0.1 for field in required_fields if field in content.lower())
        base_confidence += field_bonus
        
        # 복잡도 보정 (복잡한 명령은 신뢰도가 낮을 수 있음)
        if complexity_score > 0.7:
            base_confidence -= 0.1
        
        # 컨텍스트 활용도
        if context_analysis.get("has_project_context"):
            base_confidence += 0.1
        
        # 모호함 감지 시 신뢰도 감소
        if context_analysis.get("contains_ambiguity_indicators"):
            base_confidence -= 0.2
        
        return max(0.0, min(1.0, base_confidence))
    
    def _calculate_basic_confidence(self, content: str) -> float:
        """기본 신뢰도 계산 (폴백)"""
        if not content or len(content) < 10:
            return 0.1
        if "error" in content.lower():
            return 0.2
        if len(content) > 40:
            return 0.8
        return 0.6
    
    async def process_advanced_nlp_command(
        self, 
        user_id: str, 
        project_name: str, 
        command: str, 
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """고급 NLP 명령 처리 (MCP 도구용)"""
        if context is None:
            context = {}
        
        context["project_name"] = project_name
        context["user_id"] = user_id
        
        # 고급 처리 활성화
        original_setting = self.advanced_nlp_enabled
        self.advanced_nlp_enabled = True
        
        try:
            response = await self.process_command(command, context)
            
            # 응답을 고급 NLP 형식으로 변환
            return {
                "original_command": command,
                "user_id": user_id,
                "project_name": project_name,
                "model_response": {
                    "content": response.content,
                    "confidence": response.confidence,
                    "processing_time": response.processing_time,
                    "tokens_used": response.tokens_used
                },
                "advanced_features": {
                    "context_analysis": await self._analyze_context(command, context),
                    "complexity_score": self._evaluate_complexity(command, context),
                    "user_experience_level": self._estimate_user_experience(command, context)
                },
                "timestamp": asyncio.get_event_loop().time()
            }
            
        finally:
            # 원래 설정 복원
            self.advanced_nlp_enabled = original_setting
    
    async def get_learning_suggestions(self, user_id: str, command: str) -> List[Dict[str, Any]]:
        """학습 기반 제안 조회"""
        suggestions = []
        
        # 사용자 패턴 기반 제안
        if "deploy" in command.lower() and "replicas" not in command.lower():
            suggestions.append({
                "type": "parameter_suggestion",
                "text": "복제본 수를 지정하면 더 정확한 배포가 가능합니다. (예: '3개 복제본으로 배포')",
                "priority": "medium"
            })
        
        if "scale" in command.lower() and not any(word in command.lower() for word in ["up", "down", "to", "by"]):
            suggestions.append({
                "type": "action_clarification",
                "text": "스케일링 방향을 명시해주세요. (예: '2개로 스케일', '2개 증가')",
                "priority": "high"
            })
        
        return suggestions

class MultiModelProcessor:
    """다중 AI 모델 통합 프로세서"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.clients: Dict[ModelType, ModelClient] = {}
        self._initialize_clients()
    
    def _initialize_clients(self):
        """AI 모델 클라이언트 초기화"""
        try:
            # Claude 클라이언트
            if self.config.get("claude", {}).get("enabled", False):
                self.clients[ModelType.CLAUDE] = ClaudeClient(
                    ModelType.CLAUDE,
                    self.config["claude"]["base_url"],
                    self.config["claude"]["api_key"]
                )
            
            # GPT-4 클라이언트
            if self.config.get("gpt4", {}).get("enabled", False):
                self.clients[ModelType.GPT4] = GPT4Client(
                    ModelType.GPT4,
                    self.config["gpt4"]["base_url"],
                    self.config["gpt4"]["api_key"]
                )
            
            # Gemini 클라이언트
            if self.config.get("gemini", {}).get("enabled", False):
                self.clients[ModelType.GEMINI] = GeminiClient(
                    ModelType.GEMINI,
                    self.config["gemini"]["base_url"],
                    self.config["gemini"]["api_key"]
                )
            
            logger.info(f"Initialized {len(self.clients)} AI model clients")
            
        except Exception as e:
            logger.error(f"Failed to initialize AI model clients: {e}")
            raise
    
    async def process_command(self, command: str, context: Dict[str, Any] = None) -> ProcessedCommand:
        """명령 처리 (다중 모델 활용)"""
        if context is None:
            context = {}
        
        logger.info(f"Processing command with {len(self.clients)} models: {command}")
        
        # 모든 모델에 동시 요청
        tasks = [
            client.process_command(command, context)
            for client in self.clients.values()
        ]
        
        try:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 예외 처리
            valid_responses = []
            for i, response in enumerate(responses):
                if isinstance(response, Exception):
                    logger.error(f"Model {list(self.clients.keys())[i]} failed: {response}")
                elif response.error:
                    logger.error(f"Model {response.model_type} error: {response.error}")
                else:
                    valid_responses.append(response)
            
            if not valid_responses:
                raise Exception("All AI models failed to process the command")
            
            # 최적 응답 선택
            best_response = self._select_best_response(valid_responses)
            
            # 명령 해석
            interpreted_command = self._parse_response(best_response.content)
            
            # 제안 생성
            suggestions = self._generate_suggestions(command, interpreted_command, valid_responses)
            
            # 품질 평가
            quality = self._evaluate_quality(best_response, interpreted_command)
            
            return ProcessedCommand(
                original_command=command,
                interpreted_command=interpreted_command,
                confidence=best_response.confidence,
                suggestions=suggestions,
                model_responses=valid_responses,
                best_response=best_response,
                quality=quality
            )
            
        except Exception as e:
            logger.error(f"Multi-model processing failed: {e}")
            raise
    
    def _select_best_response(self, responses: List[ModelResponse]) -> ModelResponse:
        """최적 응답 선택"""
        # 신뢰도와 처리 시간을 고려한 점수 계산
        scored_responses = []
        
        for response in responses:
            # 기본 점수: 신뢰도
            score = response.confidence
            
            # 처리 시간 보너스 (빠른 응답에 가점)
            if response.processing_time < 2.0:
                score += 0.1
            elif response.processing_time > 5.0:
                score -= 0.1
            
            # 토큰 사용량 고려 (효율적인 응답에 가점)
            if response.tokens_used and response.tokens_used < 500:
                score += 0.05
            
            scored_responses.append((score, response))
        
        # 점수 순으로 정렬하여 최고 점수 선택
        scored_responses.sort(key=lambda x: x[0], reverse=True)
        return scored_responses[0][1]
    
    def _parse_response(self, content: str) -> Dict[str, Any]:
        """AI 응답을 구조화된 명령으로 파싱"""
        try:
            # JSON 응답 파싱 시도
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_content = content[json_start:json_end].strip()
            elif content.strip().startswith("{"):
                json_content = content.strip()
            else:
                # JSON이 아닌 경우 기본 구조 생성
                return {
                    "action": "unknown",
                    "target": "unknown",
                    "parameters": {},
                    "raw_content": content
                }
            
            return json.loads(json_content)
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return {
                "action": "unknown",
                "target": "unknown",
                "parameters": {},
                "raw_content": content,
                "parse_error": str(e)
            }
    
    def _generate_suggestions(self, original_command: str, interpreted: Dict[str, Any], responses: List[ModelResponse]) -> List[str]:
        """명령 개선 제안 생성"""
        suggestions = []
        
        # 신뢰도가 낮은 경우
        if interpreted.get("confidence", 0) < 0.7:
            suggestions.append("명령을 더 구체적으로 표현해주세요. (예: 'my-app을 staging에 3개 복제본으로 배포해줘')")
        
        # 액션이 불명확한 경우
        if interpreted.get("action") == "unknown":
            suggestions.append("원하는 작업을 명확히 해주세요. (배포, 스케일링, 롤백, 삭제 등)")
        
        # 타겟이 불명확한 경우
        if interpreted.get("target") == "unknown":
            suggestions.append("대상 앱이나 서비스 이름을 지정해주세요.")
        
        # 다른 모델들의 응답과 비교하여 제안
        if len(responses) > 1:
            actions = [r.content for r in responses if "action" in r.content.lower()]
            if len(set(actions)) > 1:
                suggestions.append("여러 해석이 가능합니다. 더 명확한 표현을 사용해보세요.")
        
        return suggestions
    
    def _evaluate_quality(self, response: ModelResponse, interpreted: Dict[str, Any]) -> ResponseQuality:
        """응답 품질 평가"""
        score = 0
        
        # 신뢰도 점수
        score += response.confidence * 40
        
        # 처리 시간 점수
        if response.processing_time < 1.0:
            score += 20
        elif response.processing_time < 3.0:
            score += 15
        elif response.processing_time < 5.0:
            score += 10
        
        # 파싱 성공 점수
        if interpreted.get("action") != "unknown":
            score += 20
        if interpreted.get("target") != "unknown":
            score += 20
        
        # 품질 등급 결정
        if score >= 80:
            return ResponseQuality.EXCELLENT
        elif score >= 60:
            return ResponseQuality.GOOD
        elif score >= 40:
            return ResponseQuality.FAIR
        else:
            return ResponseQuality.POOR
    
    async def close(self):
        """모든 클라이언트 종료"""
        for client in self.clients.values():
            await client.close()
        logger.info("All AI model clients closed")

# 설정 예시
DEFAULT_CONFIG = {
    "claude": {
        "enabled": True,
        "base_url": "https://api.anthropic.com",
        "api_key": "your-claude-api-key"
    },
    "gpt4": {
        "enabled": True,
        "base_url": "https://api.openai.com",
        "api_key": "your-openai-api-key"
    },
    "gemini": {
        "enabled": True,
        "base_url": "https://generativelanguage.googleapis.com",
        "api_key": "your-gemini-api-key"
    }
}

if __name__ == "__main__":
    # 테스트 코드
    async def test_multi_model():
        processor = MultiModelProcessor(DEFAULT_CONFIG)
        
        try:
            result = await processor.process_command(
                "my-app을 staging에 배포해줘",
                {"project_name": "test-project", "deployments": []}
            )
            
            print(f"Original: {result.original_command}")
            print(f"Interpreted: {result.interpreted_command}")
            print(f"Confidence: {result.confidence}")
            print(f"Quality: {result.quality}")
            print(f"Suggestions: {result.suggestions}")
            
        finally:
            await processor.close()
    
    asyncio.run(test_multi_model())
