import type { ProposalSummary } from '@/lib/api/types'
import type { DraftDoc } from '../draft/model'

export type LabelResolver = (id: string | null | undefined) => string

/** Resolves element ids to labels using the draft plus elements proposed by ADD proposals. */
export function makeLabelResolver(doc: DraftDoc | undefined, proposals: ProposalSummary[] | undefined): LabelResolver {
  const labels = new Map<string, string>()
  for (const element of [...(doc?.classes ?? []), ...(doc?.object_properties ?? []), ...(doc?.datatype_properties ?? [])]) {
    labels.set(element.id, element.label)
  }
  for (const proposal of proposals ?? []) {
    if (proposal.new_element_id && !labels.has(proposal.new_element_id)) {
      labels.set(proposal.new_element_id, `${proposal.target_label ?? proposal.new_element_id} (proposed)`)
    }
  }
  return (id) => (id ? (labels.get(id) ?? `Unknown (${id})`) : '—')
}
