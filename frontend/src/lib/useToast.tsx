import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Toast = { msg: string; err?: boolean } | null
const Ctx = createContext<(msg: string, err?: boolean) => void>(() => {})

export const useToast = () => useContext(Ctx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast>(null)
  const push = useCallback((msg: string, err = false) => {
    setToast({ msg, err })
    setTimeout(() => setToast(null), 4500)
  }, [])
  return (
    <Ctx.Provider value={push}>
      {children}
      {toast && <div className={`toast ${toast.err ? 'err' : ''}`}>{toast.msg}</div>}
    </Ctx.Provider>
  )
}
