import { useState, useEffect, useRef } from 'react'
import { X, ExternalLink, Loader2, CheckCircle, AlertCircle } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

interface Props {
  environment: string
  onClose: () => void
}

type Phase = 'idle' | 'started' | 'polling' | 'success' | 'error'

export default function SSOConnectModal({ environment, onClose }: Props) {
  const { startSSO, pollSSO } = useAuth()
  const [phase, setPhase] = useState<Phase>('idle')
  const [verificationUrl, setVerificationUrl] = useState('')
  const [userCode, setUserCode] = useState('')
  const [deviceCode, setDeviceCode] = useState('')
  const [pollInterval, setPollInterval] = useState(5)
  const [message, setMessage] = useState('')
  const [roleName, setRoleName] = useState('')
  const [expiresMin, setExpiresMin] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const envLabel = environment === 'prd' ? 'Prod' : 'Nonprod'

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  async function handleStart() {
    setPhase('started')
    try {
      const res = await startSSO(environment)
      setVerificationUrl(res.verification_uri_complete)
      setUserCode(res.user_code)
      setDeviceCode(res.device_code)
      setPollInterval(res.interval)
      setPhase('polling')

      // Open the SSO approval page
      window.open(res.verification_uri_complete, '_blank')

      // Start polling
      pollRef.current = setInterval(async () => {
        try {
          const poll = await pollSSO(res.device_code)
          if (poll.status === 'authenticated') {
            if (pollRef.current) clearInterval(pollRef.current)
            setRoleName(poll.role_name || '')
            setExpiresMin(poll.expires_in_minutes || 0)
            setPhase('success')
          } else if (poll.status === 'expired') {
            if (pollRef.current) clearInterval(pollRef.current)
            setMessage(poll.message || 'Expired')
            setPhase('error')
          }
          // 'pending' and 'slow_down' — keep polling
        } catch {
          // network error — keep trying
        }
      }, (res.interval + 1) * 1000)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to start SSO')
      setPhase('error')
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">
            Connect to {envLabel}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>

        {/* Idle — explain and start */}
        {phase === 'idle' && (
          <div>
            <p className="text-sm text-gray-600 mb-4">
              Authenticate with AWS SSO to query {envLabel} Redshift.
              This opens your organization's SSO login page in a new tab.
              Your credentials are stored for this session only.
            </p>
            <button
              onClick={handleStart}
              className="w-full bg-genie-600 text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-genie-700"
            >
              Start SSO Authentication
            </button>
          </div>
        )}

        {/* Started — loading */}
        {phase === 'started' && (
          <div className="flex flex-col items-center py-4">
            <Loader2 size={24} className="animate-spin text-genie-600 mb-2" />
            <p className="text-sm text-gray-600">Initiating SSO flow...</p>
          </div>
        )}

        {/* Polling — waiting for user to approve in browser */}
        {phase === 'polling' && (
          <div>
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
              <p className="text-sm text-blue-900 mb-2">
                A browser tab has opened for SSO login. Complete the sign-in there.
              </p>
              <p className="text-xs text-blue-700 mb-3">
                If the tab didn't open, click below:
              </p>
              <a
                href={verificationUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm text-blue-700 hover:text-blue-900 font-medium"
              >
                <ExternalLink size={14} />
                Open SSO Login Page
              </a>
              {userCode && (
                <p className="text-xs text-blue-600 mt-2">
                  Confirmation code: <code className="bg-blue-100 px-1.5 py-0.5 rounded font-bold">{userCode}</code>
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={14} className="animate-spin" />
              Waiting for approval...
            </div>
          </div>
        )}

        {/* Success */}
        {phase === 'success' && (
          <div>
            <div className="flex flex-col items-center py-4">
              <CheckCircle size={32} className="text-green-500 mb-2" />
              <p className="text-sm font-medium text-gray-900">Connected to {envLabel}!</p>
              <p className="text-xs text-gray-500 mt-1">
                Role: {roleName} &middot; Expires in {expiresMin} minutes
              </p>
            </div>
            <button
              onClick={onClose}
              className="w-full bg-genie-600 text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-genie-700 mt-2"
            >
              Done
            </button>
          </div>
        )}

        {/* Error */}
        {phase === 'error' && (
          <div>
            <div className="flex flex-col items-center py-4">
              <AlertCircle size={32} className="text-red-500 mb-2" />
              <p className="text-sm text-red-700">{message}</p>
            </div>
            <button
              onClick={() => setPhase('idle')}
              className="w-full bg-gray-100 text-gray-700 rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-200 mt-2"
            >
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
