import { createContext, useContext, useState, ReactNode } from 'react'

interface EnvironmentContextType {
  environment: string
  setEnvironment: (e: string) => void
}

const EnvironmentContext = createContext<EnvironmentContextType>({
  environment: 'np',
  setEnvironment: () => {},
})

export function EnvironmentProvider({ children }: { children: ReactNode }) {
  const [environment, setEnvironment] = useState('np')
  return (
    <EnvironmentContext.Provider value={{ environment, setEnvironment }}>
      {children}
    </EnvironmentContext.Provider>
  )
}

export function useEnvironment() {
  return useContext(EnvironmentContext)
}
