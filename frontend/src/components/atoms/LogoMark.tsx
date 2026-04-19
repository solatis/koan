/**
 * LogoMark — the koan geometric brand mark.
 *
 * Two overlapping circles: 16px orange (top-left) and 10px teal
 * (bottom-right). Pure CSS, no SVG. Used in: header bar.
 */

import './LogoMark.css'

interface LogoMarkProps {
  size?: number
}

export function LogoMark({ size = 20 }: LogoMarkProps) {
  return (
    <span
      className="logo-mark"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <span className="logo-mark__orange" />
      <span className="logo-mark__teal" />
    </span>
  )
}

export default LogoMark
