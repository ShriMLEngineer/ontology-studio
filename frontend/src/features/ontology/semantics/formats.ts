import type { RdfFormat } from '@/lib/api/types'

export const RDF_FORMATS: { value: RdfFormat; label: string }[] = [
  { value: 'turtle', label: 'Turtle' },
  { value: 'rdfxml', label: 'RDF/XML' },
  { value: 'jsonld', label: 'JSON-LD' },
  { value: 'ntriples', label: 'N-Triples' },
]
