import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core'

type Props = {
  icon: IconDefinition
  className?: string
  title?: string
}

export function Icon({ icon, className, title }: Props) {
  return <FontAwesomeIcon icon={icon} className={className} title={title} />
}
