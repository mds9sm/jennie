import { useState, useEffect, useCallback } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Header from './Header'
import Sidebar from './Sidebar'
import GuidedTour, { isTourCompleted } from '../onboarding/GuidedTour'
import FeatureTips from '../common/FeatureTips'

export default function MainLayout() {
  const location = useLocation()
  const [showTour, setShowTour] = useState(false)

  useEffect(() => {
    if (!isTourCompleted()) {
      // Small delay so the layout renders first and targets are measurable
      const timer = setTimeout(() => setShowTour(true), 500)
      return () => clearTimeout(timer)
    }
  }, [])

  const handleStartTour = useCallback(() => {
    setShowTour(true)
  }, [])

  return (
    <div className="h-screen flex flex-col">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar onStartTour={handleStartTour} />
        <main className="flex-1 overflow-auto bg-white flex flex-col">
          <div className="flex-1 overflow-auto">
            <Outlet />
          </div>
          <FeatureTips currentPath={location.pathname} />
        </main>
      </div>
      <GuidedTour visible={showTour} onClose={() => setShowTour(false)} />
    </div>
  )
}
