/**
 * Button — primary and secondary action triggers.
 *
 * Used for: "Start Run", "Next", "Send", "Use Defaults",
 * and other interactive actions throughout the UI.
 */

import './Button.css'
import type { ReactNode, ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary'
type Size = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant: Variant
  size?: Size
  children: ReactNode
}

export function Button({ variant, size = 'md', children, className, ...rest }: ButtonProps) {
  const cls = `atom-btn atom-btn--${variant} atom-btn--${size}${className ? ` ${className}` : ''}`
  return (
    <button className={cls} {...rest}>
      {children}
    </button>
  )
}

export default Button
