import './CiteChip.css'

interface CiteChipProps {
  seq: string
  onClick?: () => void
}

export function CiteChip({ seq, onClick }: CiteChipProps) {
  return (
    <span className="atom-cite-chip" role="button" tabIndex={0} onClick={onClick}>
      {seq}
    </span>
  )
}

export default CiteChip
