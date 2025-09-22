/**
 * Slack 연동 컴포넌트
 * 사용자가 쉽게 Slack을 연동할 수 있도록 도와주는 UI
 */

import React, { useState, useEffect } from 'react';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { Input } from './ui/Input';
import { Select } from './ui/Select';

interface SlackChannel {
  id: string;
  name: string;
  is_private: boolean;
  is_member: boolean;
}

interface SlackIntegrationProps {
  onIntegrationComplete?: (config: SlackConfig) => void;
}

interface SlackConfig {
  access_token: string;
  default_channel: string;
  deployment_channel: string;
  error_channel: string;
}

export const SlackIntegration: React.FC<SlackIntegrationProps> = ({
  onIntegrationComplete
}) => {
  const [step, setStep] = useState<'auth' | 'channels' | 'config' | 'test' | 'complete'>('auth');
  const [authUrl, setAuthUrl] = useState<string>('');
  const [accessToken, setAccessToken] = useState<string>('');
  const [channels, setChannels] = useState<SlackChannel[]>([]);
  const [config, setConfig] = useState<Partial<SlackConfig>>({
    default_channel: '#general',
    deployment_channel: '#deployments',
    error_channel: '#alerts'
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  // 1단계: Slack 인증 URL 생성
  const generateAuthUrl = async () => {
    setLoading(true);
    setError('');
    
    try {
      const redirectUri = `${window.location.origin}/slack/callback`;
      const response = await fetch(`/api/v1/slack/auth/url?redirect_uri=${encodeURIComponent(redirectUri)}`);
      const data = await response.json();
      
      if (data.auth_url) {
        setAuthUrl(data.auth_url);
        setStep('auth');
      } else {
        setError('인증 URL 생성에 실패했습니다.');
      }
    } catch (err) {
      setError('인증 URL 생성 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  // 2단계: 인증 완료 후 채널 목록 조회
  const handleAuthCallback = async (code: string) => {
    setLoading(true);
    setError('');
    
    try {
      const response = await fetch(`/api/v1/slack/auth/callback?code=${code}`);
      const data = await response.json();
      
      if (data.success) {
        setAccessToken(data.access_token);
        setChannels(data.channels || []);
        setStep('channels');
      } else {
        setError(data.message || 'Slack 인증에 실패했습니다.');
      }
    } catch (err) {
      setError('Slack 인증 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  // 3단계: 채널 설정
  const handleChannelConfig = () => {
    setStep('config');
  };

  // 4단계: 설정 저장 및 테스트
  const saveConfig = async () => {
    if (!accessToken) {
      setError('액세스 토큰이 없습니다.');
      return;
    }

    setLoading(true);
    setError('');
    
    try {
      // 설정 저장
      const response = await fetch('/api/v1/slack/save-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          access_token: accessToken,
          ...config
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        setStep('test');
        // 테스트 메시지 전송
        await sendTestMessage();
      } else {
        setError(data.message || '설정 저장에 실패했습니다.');
      }
    } catch (err) {
      setError('설정 저장 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  // 테스트 메시지 전송
  const sendTestMessage = async () => {
    if (!accessToken) return;
    
    try {
      const response = await fetch(`/api/v1/slack/test?access_token=${accessToken}&channel=${config.default_channel}`);
      const data = await response.json();
      
      if (data.success) {
        setStep('complete');
        onIntegrationComplete?.(config as SlackConfig);
      } else {
        setError(data.message || '테스트 메시지 전송에 실패했습니다.');
      }
    } catch (err) {
      setError('테스트 메시지 전송 중 오류가 발생했습니다.');
    }
  };

  // URL에서 인증 코드 확인
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    const error = urlParams.get('error');
    
    if (code) {
      handleAuthCallback(code);
    } else if (error) {
      setError(`Slack 인증 오류: ${error}`);
    }
  }, []);

  return (
    <div className="max-w-2xl mx-auto p-6">
      <Card>
        <div className="p-6">
          <h2 className="text-2xl font-bold mb-6">Slack 연동 설정</h2>
          
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
              {error}
            </div>
          )}

          {/* 1단계: 인증 */}
          {step === 'auth' && (
            <div className="text-center">
              <div className="mb-6">
                <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <span className="text-2xl">🔗</span>
                </div>
                <h3 className="text-xl font-semibold mb-2">Slack 계정 연결</h3>
                <p className="text-gray-600 mb-6">
                  K-Le-PaaS에서 Slack 알림을 받으려면 먼저 Slack 계정을 연결해야 합니다.
                </p>
              </div>
              
              <Button
                onClick={generateAuthUrl}
                disabled={loading}
                className="bg-green-600 hover:bg-green-700 text-white px-6 py-3 rounded-lg"
              >
                {loading ? '연결 중...' : 'Slack 계정 연결하기'}
              </Button>
              
              {authUrl && (
                <div className="mt-4">
                  <a
                    href={authUrl}
                    className="text-blue-600 hover:text-blue-800 underline"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    또는 여기를 클릭하여 Slack 인증 페이지로 이동
                  </a>
                </div>
              )}
            </div>
          )}

          {/* 2단계: 채널 목록 */}
          {step === 'channels' && (
            <div>
              <div className="mb-6">
                <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <span className="text-2xl">📋</span>
                </div>
                <h3 className="text-xl font-semibold mb-2">사용 가능한 채널</h3>
                <p className="text-gray-600 mb-6">
                  다음 채널들에 알림을 보낼 수 있습니다.
                </p>
              </div>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                {channels.map((channel) => (
                  <div
                    key={channel.id}
                    className="p-4 border rounded-lg hover:bg-gray-50"
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-medium">#{channel.name}</span>
                        {channel.is_private && (
                          <span className="ml-2 text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
                            비공개
                          </span>
                        )}
                      </div>
                      {channel.is_member && (
                        <span className="text-xs bg-green-100 text-green-800 px-2 py-1 rounded">
                          멤버
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              
              <Button
                onClick={handleChannelConfig}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white"
              >
                다음 단계로
              </Button>
            </div>
          )}

          {/* 3단계: 채널 설정 */}
          {step === 'config' && (
            <div>
              <div className="mb-6">
                <div className="w-16 h-16 bg-purple-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <span className="text-2xl">⚙️</span>
                </div>
                <h3 className="text-xl font-semibold mb-2">알림 채널 설정</h3>
                <p className="text-gray-600 mb-6">
                  각 종류의 알림을 받을 채널을 선택하세요.
                </p>
              </div>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    기본 알림 채널
                  </label>
                  <Select
                    value={config.default_channel}
                    onChange={(value) => setConfig(prev => ({ ...prev, default_channel: value }))}
                    options={channels.map(ch => ({ value: `#${ch.name}`, label: `#${ch.name}` }))}
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    배포 알림 채널
                  </label>
                  <Select
                    value={config.deployment_channel}
                    onChange={(value) => setConfig(prev => ({ ...prev, deployment_channel: value }))}
                    options={channels.map(ch => ({ value: `#${ch.name}`, label: `#${ch.name}` }))}
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    에러 알림 채널
                  </label>
                  <Select
                    value={config.error_channel}
                    onChange={(value) => setConfig(prev => ({ ...prev, error_channel: value }))}
                    options={channels.map(ch => ({ value: `#${ch.name}`, label: `#${ch.name}` }))}
                  />
                </div>
              </div>
              
              <Button
                onClick={saveConfig}
                disabled={loading}
                className="w-full mt-6 bg-purple-600 hover:bg-purple-700 text-white"
              >
                {loading ? '설정 저장 중...' : '설정 저장 및 테스트'}
              </Button>
            </div>
          )}

          {/* 4단계: 테스트 */}
          {step === 'test' && (
            <div className="text-center">
              <div className="mb-6">
                <div className="w-16 h-16 bg-yellow-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <span className="text-2xl">🧪</span>
                </div>
                <h3 className="text-xl font-semibold mb-2">테스트 메시지 전송 중</h3>
                <p className="text-gray-600 mb-6">
                  {config.default_channel}에 테스트 메시지를 전송하고 있습니다...
                </p>
              </div>
              
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
            </div>
          )}

          {/* 5단계: 완료 */}
          {step === 'complete' && (
            <div className="text-center">
              <div className="mb-6">
                <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <span className="text-2xl">✅</span>
                </div>
                <h3 className="text-xl font-semibold mb-2">Slack 연동 완료!</h3>
                <p className="text-gray-600 mb-6">
                  {config.default_channel}에 테스트 메시지가 전송되었습니다.
                  이제 K-Le-PaaS에서 Slack 알림을 받을 수 있습니다!
                </p>
              </div>
              
              <Button
                onClick={() => window.location.reload()}
                className="bg-green-600 hover:bg-green-700 text-white px-6 py-3 rounded-lg"
              >
                완료
              </Button>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
};
