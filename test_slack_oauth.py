#!/usr/bin/env python3
"""
Slack OAuth 2.0 연동 테스트 스크립트
사용자 친화적인 Slack 연동을 테스트합니다.
"""

import asyncio
import httpx
import json
from urllib.parse import urlencode

# 테스트 설정
BASE_URL = "http://localhost:8000"
REDIRECT_URI = "http://localhost:8000/slack/callback"

async def test_slack_oauth():
    """Slack OAuth 연동 테스트"""
    print("🚀 Slack OAuth 연동 테스트 시작")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            # 1. 인증 URL 생성 테스트
            print("\n1️⃣ 인증 URL 생성 테스트")
            print("-" * 30)
            
            auth_url_response = await client.get(
                f"{BASE_URL}/api/v1/slack/auth/url",
                params={"redirect_uri": REDIRECT_URI}
            )
            
            if auth_url_response.status_code == 200:
                auth_data = auth_url_response.json()
                print(f"✅ 인증 URL 생성 성공")
                print(f"📋 인증 URL: {auth_data['auth_url']}")
                print(f"🔑 State: {auth_data['state']}")
                
                # 사용자에게 인증 URL 안내
                print(f"\n🌐 브라우저에서 다음 URL을 열어주세요:")
                print(f"   {auth_data['auth_url']}")
                print(f"\n📝 인증 완료 후 받은 'code' 값을 입력해주세요:")
                
                # 사용자 입력 대기
                auth_code = input("인증 코드 (code): ").strip()
                
                if not auth_code:
                    print("❌ 인증 코드가 입력되지 않았습니다.")
                    return
                
                # 2. 인증 코드를 토큰으로 교환
                print(f"\n2️⃣ 토큰 교환 테스트")
                print("-" * 30)
                
                token_response = await client.get(
                    f"{BASE_URL}/api/v1/slack/auth/callback",
                    params={"code": auth_code, "state": auth_data['state']}
                )
                
                if token_response.status_code == 200:
                    token_data = token_response.json()
                    if token_data.get('success'):
                        print("✅ 토큰 교환 성공")
                        print(f"🔑 액세스 토큰: {token_data['access_token'][:20]}...")
                        print(f"🏢 팀 ID: {token_data['team_id']}")
                        print(f"👤 사용자 ID: {token_data['user_id']}")
                        
                        access_token = token_data['access_token']
                        
                        # 3. 채널 목록 조회
                        print(f"\n3️⃣ 채널 목록 조회 테스트")
                        print("-" * 30)
                        
                        channels_response = await client.get(
                            f"{BASE_URL}/api/v1/slack/channels",
                            params={"access_token": access_token}
                        )
                        
                        if channels_response.status_code == 200:
                            channels_data = channels_response.json()
                            if channels_data.get('success'):
                                channels = channels_data['channels']
                                print(f"✅ 채널 목록 조회 성공 ({len(channels)}개 채널)")
                                
                                for i, channel in enumerate(channels[:5]):  # 처음 5개만 표시
                                    print(f"   {i+1}. #{channel['name']} {'(비공개)' if channel['is_private'] else ''}")
                                
                                if len(channels) > 5:
                                    print(f"   ... 외 {len(channels) - 5}개 채널")
                                
                                # 4. 테스트 메시지 전송
                                print(f"\n4️⃣ 테스트 메시지 전송")
                                print("-" * 30)
                                
                                # 첫 번째 채널로 테스트 메시지 전송
                                test_channel = f"#{channels[0]['name']}" if channels else "#general"
                                
                                test_response = await client.post(
                                    f"{BASE_URL}/api/v1/slack/test",
                                    params={
                                        "access_token": access_token,
                                        "channel": test_channel
                                    }
                                )
                                
                                if test_response.status_code == 200:
                                    test_data = test_response.json()
                                    if test_data.get('success'):
                                        print(f"✅ 테스트 메시지 전송 성공")
                                        print(f"📨 채널: {test_channel}")
                                        print(f"⏰ 메시지 시간: {test_data.get('message_ts', 'N/A')}")
                                        print(f"\n🎉 Slack 연동이 완료되었습니다!")
                                        print(f"   {test_channel} 채널을 확인해보세요.")
                                    else:
                                        print(f"❌ 테스트 메시지 전송 실패: {test_data.get('message', 'Unknown error')}")
                                else:
                                    print(f"❌ 테스트 메시지 전송 요청 실패: {test_response.status_code}")
                                    print(f"   응답: {test_response.text}")
                            else:
                                print(f"❌ 채널 목록 조회 실패: {channels_data.get('message', 'Unknown error')}")
                        else:
                            print(f"❌ 채널 목록 조회 요청 실패: {channels_response.status_code}")
                            print(f"   응답: {channels_response.text}")
                    else:
                        print(f"❌ 토큰 교환 실패: {token_data.get('message', 'Unknown error')}")
                else:
                    print(f"❌ 토큰 교환 요청 실패: {token_response.status_code}")
                    print(f"   응답: {token_response.text}")
            else:
                print(f"❌ 인증 URL 생성 실패: {auth_url_response.status_code}")
                print(f"   응답: {auth_url_response.text}")
                
        except Exception as e:
            print(f"❌ 테스트 중 오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()

async def test_with_bot_token():
    """Bot Token을 사용한 직접 테스트"""
    print("\n🤖 Bot Token을 사용한 직접 테스트")
    print("=" * 50)
    
    # Bot Token 입력 받기
    bot_token = input("Bot Token (xoxb-로 시작): ").strip()
    
    if not bot_token or not bot_token.startswith('xoxb-'):
        print("❌ 올바른 Bot Token을 입력해주세요.")
        return
    
    try:
        # Slack API 직접 호출
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. 인증 테스트
            print("\n1️⃣ 인증 테스트")
            print("-" * 30)
            
            auth_response = await client.get(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"}
            )
            
            if auth_response.status_code == 200:
                auth_data = auth_response.json()
                if auth_data.get('ok'):
                    print("✅ Bot Token 인증 성공")
                    print(f"🏢 팀: {auth_data.get('team')}")
                    print(f"👤 사용자: {auth_data.get('user')}")
                    print(f"🤖 봇: {auth_data.get('bot_id')}")
                else:
                    print(f"❌ Bot Token 인증 실패: {auth_data.get('error')}")
                    return
            else:
                print(f"❌ 인증 요청 실패: {auth_response.status_code}")
                return
            
            # 2. 채널 목록 조회
            print("\n2️⃣ 채널 목록 조회")
            print("-" * 30)
            
            channels_response = await client.get(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {bot_token}"},
                params={"types": "public_channel,private_channel", "limit": 10}
            )
            
            if channels_response.status_code == 200:
                channels_data = channels_response.json()
                if channels_data.get('ok'):
                    channels = channels_data.get('channels', [])
                    print(f"✅ 채널 목록 조회 성공 ({len(channels)}개 채널)")
                    
                    for i, channel in enumerate(channels[:5]):
                        print(f"   {i+1}. #{channel['name']} {'(비공개)' if channel['is_private'] else ''}")
                    
                    # 3. 테스트 메시지 전송
                    if channels:
                        test_channel = channels[0]['id']
                        print(f"\n3️⃣ 테스트 메시지 전송 (#{channels[0]['name']})")
                        print("-" * 30)
                        
                        message_response = await client.post(
                            "https://slack.com/api/chat.postMessage",
                            headers={"Authorization": f"Bearer {bot_token}"},
                            json={
                                "channel": test_channel,
                                "text": "🎉 K-Le-PaaS Bot Token 테스트 성공!\n\n이 메시지가 보이면 Bot Token 연동이 완료된 것입니다!",
                                "blocks": [
                                    {
                                        "type": "header",
                                        "text": {
                                            "type": "plain_text",
                                            "text": "🎉 K-Le-PaaS Bot Token 테스트"
                                        }
                                    },
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": "Bot Token을 사용한 직접 연동이 성공적으로 완료되었습니다!"
                                        }
                                    }
                                ]
                            }
                        )
                        
                        if message_response.status_code == 200:
                            message_data = message_response.json()
                            if message_data.get('ok'):
                                print("✅ 테스트 메시지 전송 성공")
                                print(f"⏰ 메시지 시간: {message_data.get('ts')}")
                                print(f"\n🎉 Bot Token 연동이 완료되었습니다!")
                            else:
                                print(f"❌ 테스트 메시지 전송 실패: {message_data.get('error')}")
                        else:
                            print(f"❌ 메시지 전송 요청 실패: {message_response.status_code}")
                    else:
                        print("❌ 사용 가능한 채널이 없습니다.")
                else:
                    print(f"❌ 채널 목록 조회 실패: {channels_data.get('error')}")
            else:
                print(f"❌ 채널 목록 조회 요청 실패: {channels_response.status_code}")
                
    except Exception as e:
        print(f"❌ Bot Token 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()

async def main():
    """메인 테스트 함수"""
    print("🔧 Slack 연동 테스트 도구")
    print("=" * 50)
    print("1. OAuth 2.0 플로우 테스트 (서버 필요)")
    print("2. Bot Token 직접 테스트 (서버 불필요)")
    print("3. 종료")
    
    choice = input("\n선택하세요 (1-3): ").strip()
    
    if choice == "1":
        print("\n⚠️  서버가 실행 중인지 확인하세요: python -m uvicorn app.main:app --reload --port 8000")
        input("서버가 실행 중이면 Enter를 눌러주세요...")
        await test_slack_oauth()
    elif choice == "2":
        await test_with_bot_token()
    elif choice == "3":
        print("👋 테스트를 종료합니다.")
    else:
        print("❌ 잘못된 선택입니다.")

if __name__ == "__main__":
    asyncio.run(main())
