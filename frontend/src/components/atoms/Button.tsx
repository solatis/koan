/**
 * Button — action triggers in primary, secondary, danger, teal, and text variants.
 *
 * Used for: "Start Run", "Next", "Send" (primary), "Cancel", "Use Defaults"
 * (secondary), "Delete" (danger), "Detect", "Explore" (teal),
 * "+ New profile", "+ Add installation" (text).
 */

import './Button.css'
import type { ReactNode, ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'teal' | 'text'
type Size = 'xs' | 'sm' | 'md'

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
