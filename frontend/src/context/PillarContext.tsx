import { createContext, useContext, useState, ReactNode } from 'react'

interface PillarContextType {
  pillar: string | null
  setPillar: (p: string | null) => void
}

const PillarContext = createContext<PillarContextType>({ pillar: null, setPillar: () => {} })

export function PillarProvider({ children }: { children: ReactNode }) {
  const [pillar, setPillar] = useState<string | null>(null)
  return <PillarContext.Provider value={{ pillar, setPillar }}>{children}</PillarContext.Provider>
}

export function usePillar() {
  return useContext(PillarContext)
}
