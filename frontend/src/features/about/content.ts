import {
  Activity,
  Bot,
  Boxes,
  Cable,
  ClipboardCheck,
  Compass,
  Cpu,
  Database,
  FileCode,
  FileText,
  FlaskConical,
  Gauge,
  KeyRound,
  Layers,
  LayoutDashboard,
  ListChecks,
  Map as MapIcon,
  Monitor,
  Network,
  Package,
  PencilRuler,
  Rocket,
  ScrollText,
  Server,
  Share2,
  Shapes,
  SlidersHorizontal,
  Sparkles,
  Users,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

export type AppArea = 'workspace' | 'ontology' | 'knowledge-graph' | 'settings'

export interface AppLink {
  area: AppArea
  tab?: string
}

export type LabelledLink = AppLink & { label: string }

export function appHref(projectId: string, link: AppLink): string {
  const base = `/projects/${projectId}/${link.area}`
  return link.tab ? `${base}?tab=${link.tab}` : base
}

/* ------------------------------------------------------------------ page sections */

export const SECTIONS = [
  { id: 'overview', label: 'Overview', icon: Compass, blurb: 'What the studio is and who it is for' },
  { id: 'lifecycle', label: 'How it works', icon: Workflow, blurb: 'The governed lifecycle, step by step' },
  { id: 'tour', label: 'Product tour', icon: MapIcon, blurb: 'Where every capability lives' },
  { id: 'architecture', label: 'Architecture', icon: Layers, blurb: 'How the system fits together' },
  { id: 'technology', label: 'Technology', icon: Cpu, blurb: 'Frameworks, libraries and standards' },
  { id: 'system', label: 'Live system', icon: Activity, blurb: 'Status of this running instance' },
] as const

export type SectionId = (typeof SECTIONS)[number]['id']

/* ------------------------------------------------------------------ overview */

export const AT_A_GLANCE = [
  { value: '9', label: 'lifecycle stages' },
  { value: '10', label: 'persisted build stages' },
  { value: '7', label: 'graph database targets' },
  { value: '5', label: 'LLM provider types' },
] as const

export interface Principle {
  icon: LucideIcon
  title: string
  summary: string
  points: readonly string[]
  link: LabelledLink
}

export const PRINCIPLES: readonly Principle[] = [
  {
    icon: Sparkles,
    title: 'LLMs assist discovery',
    summary: 'AI proposes; it never decides.',
    points: [
      'Output only ever becomes pending proposals',
      'Every quote is verified against the source text',
      'Invented ids are rejected, duplicates re-classified',
    ],
    link: { area: 'ontology', tab: 'discovery', label: 'See AI Discovery' },
  },
  {
    icon: Users,
    title: 'Domain experts govern meaning',
    summary: 'People approve what the ontology means.',
    points: [
      'Nothing reaches the draft without an SME decision',
      'Published versions are immutable snapshots',
      'Every decision and comment is kept in a review trail',
    ],
    link: { area: 'ontology', tab: 'review', label: 'See SME Review' },
  },
  {
    icon: ClipboardCheck,
    title: 'Engineering enforces consistency',
    summary: 'Deterministic rules keep the graph honest.',
    points: [
      'Structural validation and SHACL shapes gate publication',
      'Facts are accepted, rejected or quarantined with reasons',
      'Optimistic locking and an append-only audit trail',
    ],
    link: { area: 'knowledge-graph', tab: 'facts', label: 'See Fact Validation' },
  },
]

export interface Role {
  id: string
  label: string
  icon: LucideIcon
  summary: string
  steps: readonly string[]
  cta: LabelledLink
}

export const ROLES: readonly Role[] = [
  {
    id: 'engineer',
    label: 'Ontology engineer',
    icon: PencilRuler,
    summary: 'Models the domain and keeps the ontology correct.',
    steps: [
      'Design classes, relationships and attributes on the visual canvas',
      'Validate the draft and import or export RDF / OWL',
      'Publish an immutable version to the registry',
    ],
    cta: { label: 'Open the Ontology Designer', area: 'ontology', tab: 'designer' },
  },
  {
    id: 'sme',
    label: 'Domain expert (SME)',
    icon: Users,
    summary: 'Decides what the ontology means.',
    steps: [
      'Review AI proposals next to the evidence quoted from the source',
      'Approve, reject or request refinement, with a comment',
      'Apply approved changes to the draft',
    ],
    cta: { label: 'Open SME Review', area: 'ontology', tab: 'review' },
  },
  {
    id: 'data',
    label: 'Data / KG engineer',
    icon: Database,
    summary: 'Turns source data into a trustworthy knowledge graph.',
    steps: [
      'Map CSV sources and attach documents to a published ontology version',
      'Build the graph and inspect rejected and quarantined facts',
      'Deploy to a graph database and explore it with provenance',
    ],
    cta: { label: 'Open the KG Pipeline', area: 'knowledge-graph', tab: 'pipeline' },
  },
]

/* ------------------------------------------------------------------ lifecycle */

export type StageKey =
  | 'sources'
  | 'discovery'
  | 'review'
  | 'validation'
  | 'publication'
  | 'mapping'
  | 'kg_build'
  | 'deployment'
  | 'evaluation'

export type LaneKey = 'governance' | 'knowledge-graph'

export interface LifecycleStep {
  key: StageKey
  label: string
  lane: LaneKey
  optional?: boolean
  summary: string
  guardrail: string
  link: LabelledLink
}

export const LANES: Record<LaneKey, { label: string; blurb: string }> = {
  governance: { label: 'Ontology governance', blurb: 'Design, review and publish the ontology.' },
  'knowledge-graph': { label: 'Knowledge graph', blurb: 'Build and deploy graphs against a published version.' },
}

export const LIFECYCLE: readonly LifecycleStep[] = [
  {
    key: 'sources',
    label: 'Sources',
    lane: 'governance',
    summary: 'Upload documents (PDF or text) for discovery and structured data (CSV / TSV) for knowledge-graph builds.',
    guardrail: 'Sources are previewed before use and parsed into text chunks; nothing is invented from them.',
    link: { area: 'ontology', tab: 'discovery', label: 'Open sources in AI Discovery' },
  },
  {
    key: 'discovery',
    label: 'AI discovery',
    lane: 'governance',
    optional: true,
    summary:
      'An LLM reads the documents against the current draft or a published version and proposes ADD, REUSE, ALIAS, MODIFY and CONFLICT changes.',
    guardrail: 'Findings whose evidence quote cannot be found in the source are discarded and listed with the reason.',
    link: { area: 'ontology', tab: 'discovery', label: 'Open AI Discovery' },
  },
  {
    key: 'review',
    label: 'SME review',
    lane: 'governance',
    optional: true,
    summary:
      'Domain experts compare current and proposed values with evidence and validation impact, then approve, reject or request refinement.',
    guardrail: 'Nothing changes the draft until an expert approves and explicitly applies the proposal.',
    link: { area: 'ontology', tab: 'review', label: 'Open SME Review' },
  },
  {
    key: 'validation',
    label: 'Validation',
    lane: 'governance',
    summary: 'Structural rules check the saved draft; SHACL well-formedness and an OWL 2 RL reasoning preview add further lanes.',
    guardrail: 'Validation errors block publication; each finding links back to the affected element.',
    link: { area: 'ontology', tab: 'validation', label: 'Open Validation' },
  },
  {
    key: 'publication',
    label: 'Publication',
    lane: 'governance',
    summary: 'Publish an immutable, semantically versioned package (Turtle, RDF/XML, JSON-LD, N-Triples, JSON and SHACL) to the registry.',
    guardrail: 'Published versions are write-once, checksummed and never edited, only superseded.',
    link: { area: 'ontology', tab: 'registry', label: 'Open the Registry' },
  },
  {
    key: 'mapping',
    label: 'Source mapping',
    lane: 'knowledge-graph',
    summary: 'Map each structured source to classes, attributes and relationships of the published version, with suggestions and live validation.',
    guardrail: 'A build binds to exactly one published version, which is the schema authority.',
    link: { area: 'knowledge-graph', tab: 'pipeline', label: 'Open the Pipeline' },
  },
  {
    key: 'kg_build',
    label: 'KG build',
    lane: 'knowledge-graph',
    summary: 'Extract facts from records and documents, resolve entities and validate them structurally, with SHACL and against their evidence.',
    guardrail: 'Facts are accepted, rejected or quarantined with reasons and are never silently repaired.',
    link: { area: 'knowledge-graph', tab: 'facts', label: 'Open Fact Validation' },
  },
  {
    key: 'deployment',
    label: 'Graph deployment',
    lane: 'knowledge-graph',
    summary: 'Project the accepted facts to an RDF or property graph and deploy them to the selected graph database.',
    guardrail: 'A compatibility report states what is lost, and every deployment is verified by reading counts back.',
    link: { area: 'knowledge-graph', tab: 'deployments', label: 'Open Deployments' },
  },
  {
    key: 'evaluation',
    label: 'Evaluation & feedback',
    lane: 'knowledge-graph',
    summary: 'Review quality metrics with explicit denominators and send ontology gaps back to SME review as change proposals.',
    guardrail: 'Closing the loop creates proposals only; the ontology changes through the same governed path.',
    link: { area: 'knowledge-graph', tab: 'evaluation', label: 'Open Evaluation & Feedback' },
  },
]

/* ------------------------------------------------------------------ product tour */

export interface TourFeature {
  title: string
  description: string
  icon: LucideIcon
  link: AppLink
}

export interface TourArea {
  id: string
  label: string
  icon: LucideIcon
  blurb: string
  open: LabelledLink
  features: readonly TourFeature[]
}

export const TOUR: readonly TourArea[] = [
  {
    id: 'workspace',
    label: 'Project Workspace',
    icon: LayoutDashboard,
    blurb: 'Your project at a glance and the home of the lifecycle navigator.',
    open: { area: 'workspace', label: 'Open the Workspace' },
    features: [
      {
        title: 'Project overview',
        description: 'Ontology statistics, validation status, pending reviews, published versions and the latest build.',
        icon: LayoutDashboard,
        link: { area: 'workspace' },
      },
      {
        title: 'Lifecycle navigator',
        description: 'An iteration-aware workflow whose stage statuses come from real records, with reused outputs and frozen history.',
        icon: Workflow,
        link: { area: 'workspace' },
      },
      {
        title: 'Data sources',
        description: 'Browse uploaded documents and structured files, with a preview of their contents.',
        icon: FileText,
        link: { area: 'workspace' },
      },
      {
        title: 'Activity trail',
        description: 'An append-only audit trail of who changed what, and when.',
        icon: ScrollText,
        link: { area: 'workspace' },
      },
    ],
  },
  {
    id: 'ontology',
    label: 'Ontology Studio',
    icon: Network,
    blurb: 'Design, discover, review, validate and publish the ontology.',
    open: { area: 'ontology', tab: 'designer', label: 'Open Ontology Studio' },
    features: [
      {
        title: 'Ontology Designer',
        description: 'Draw classes, relationships and attributes on a visual canvas; edit hierarchy, aliases and OWL semantics in inspectors.',
        icon: PencilRuler,
        link: { area: 'ontology', tab: 'designer' },
      },
      {
        title: 'AI Discovery',
        description: 'Upload documents and let an LLM propose evidence-backed changes against the draft or a published version.',
        icon: Sparkles,
        link: { area: 'ontology', tab: 'discovery' },
      },
      {
        title: 'SME Review',
        description: 'Compare current and proposed values, inspect evidence and validation impact, then decide and apply.',
        icon: Users,
        link: { area: 'ontology', tab: 'review' },
      },
      {
        title: 'Validation',
        description: 'Structural rules with persisted reports; jump from any finding to the element it concerns.',
        icon: ListChecks,
        link: { area: 'ontology', tab: 'validation' },
      },
      {
        title: 'RDF / OWL',
        description: 'Preview OWL in four syntaxes, import RDF without losing axioms and run an OWL 2 RL reasoning preview.',
        icon: FileCode,
        link: { area: 'ontology', tab: 'semantics' },
      },
      {
        title: 'SHACL Shapes',
        description: 'Generate, author and validate shapes; malformed shapes block publication.',
        icon: Shapes,
        link: { area: 'ontology', tab: 'shapes' },
      },
      {
        title: 'Registry',
        description: 'Publish immutable versions, compare them and download checksummed packages.',
        icon: Package,
        link: { area: 'ontology', tab: 'registry' },
      },
    ],
  },
  {
    id: 'knowledge-graph',
    label: 'Knowledge Graph Studio',
    icon: Share2,
    blurb: 'Build, validate, explore and deploy knowledge graphs.',
    open: { area: 'knowledge-graph', tab: 'pipeline', label: 'Open Knowledge Graph Studio' },
    features: [
      {
        title: 'Pipeline',
        description: 'Map CSV and PDF sources to a published ontology version and run a ten-stage build with live logs.',
        icon: Cable,
        link: { area: 'knowledge-graph', tab: 'pipeline' },
      },
      {
        title: 'Graph Explorer',
        description: 'Search and filter the graph on a Cytoscape canvas; open any node or edge to see its provenance.',
        icon: Share2,
        link: { area: 'knowledge-graph', tab: 'explorer' },
      },
      {
        title: 'Fact Validation',
        description: 'Every candidate fact with its accepted, rejected or quarantined status, evidence and reasons.',
        icon: ClipboardCheck,
        link: { area: 'knowledge-graph', tab: 'facts' },
      },
      {
        title: 'Evaluation & Feedback',
        description: 'Quality metrics with explicit denominators, and ontology gaps you can send back to SME review.',
        icon: Gauge,
        link: { area: 'knowledge-graph', tab: 'evaluation' },
      },
      {
        title: 'Deployments',
        description: 'Deploy a build to a graph database with a compatibility report, then query it read-only.',
        icon: Rocket,
        link: { area: 'knowledge-graph', tab: 'deployments' },
      },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: SlidersHorizontal,
    blurb: 'Register the models and graph databases the studio can use.',
    open: { area: 'settings', label: 'Open Settings' },
    features: [
      {
        title: 'LLM models',
        description: 'Register OpenAI, Anthropic, Azure AI Foundry, Ollama or compatible endpoints and test them for real.',
        icon: Bot,
        link: { area: 'settings' },
      },
      {
        title: 'Graph databases',
        description: 'A provider-aware registry with read-only connection tests and capability flags.',
        icon: Database,
        link: { area: 'settings' },
      },
      {
        title: 'Project defaults',
        description: 'Choose the default LLM and graph database per project; every run can still override them.',
        icon: SlidersHorizontal,
        link: { area: 'settings' },
      },
      {
        title: 'Credentials stay out of the app',
        description: 'Settings keeps only the name of an environment variable, never the secret itself.',
        icon: KeyRound,
        link: { area: 'settings' },
      },
    ],
  },
]

/* ------------------------------------------------------------------ technology */

export const TECH_CATEGORIES = {
  frontend: { label: 'Frontend', icon: Monitor },
  canvas: { label: 'Canvas & graphs', icon: Share2 },
  backend: { label: 'Backend', icon: Server },
  semantics: { label: 'Semantics', icon: FileCode },
  ai: { label: 'AI & documents', icon: Bot },
  stores: { label: 'Data & graph stores', icon: Database },
  quality: { label: 'Quality', icon: FlaskConical },
} as const

export type TechCategory = keyof typeof TECH_CATEGORIES

export interface Technology {
  name: string
  category: TechCategory
  role: string
  usage: string
}

export const TECHNOLOGIES = {
  react: { name: 'React 19', category: 'frontend', role: 'UI library', usage: 'The component model behind every screen, form and dialog.' },
  typescript: { name: 'TypeScript', category: 'frontend', role: 'Type system', usage: 'Typed API contracts and view models across the whole frontend.' },
  vite: { name: 'Vite', category: 'frontend', role: 'Build tool and dev server', usage: 'Hot-reload dev server that proxies /api, and code-splitting of the Graph Explorer.' },
  tailwind: { name: 'Tailwind CSS v4', category: 'frontend', role: 'Styling', usage: 'Utility-first styling driven by CSS design tokens.' },
  shadcn: { name: 'shadcn/ui + Radix UI', category: 'frontend', role: 'Accessible components', usage: 'Dialogs, tabs, selects, tooltips and menus with keyboard and screen-reader support.' },
  tanstack: { name: 'TanStack Query', category: 'frontend', role: 'Server-state management', usage: 'Caching, invalidation and polling for build progress, health and lists.' },
  router: { name: 'React Router', category: 'frontend', role: 'Routing', usage: 'Project-scoped routes, ?tab= deep links and the unsaved-changes guard.' },
  lucide: { name: 'Lucide + Sonner', category: 'frontend', role: 'Icons and toasts', usage: 'Iconography and non-blocking notifications.' },

  reactflow: { name: 'React Flow', category: 'canvas', role: 'Node-based canvas', usage: 'Ontology Designer, the lifecycle navigator and the architecture map on this page.' },
  cytoscape: { name: 'Cytoscape.js', category: 'canvas', role: 'Graph visualisation', usage: 'Knowledge-graph explorer: layouts, filters, search highlighting and provenance drawer.' },

  python: { name: 'Python 3.12+', category: 'backend', role: 'Language', usage: 'A typed, modular monolith with framework-free domain functions.' },
  fastapi: { name: 'FastAPI', category: 'backend', role: 'Web framework', usage: 'REST API under /api with generated OpenAPI documentation at /docs.' },
  pydantic: { name: 'Pydantic v2', category: 'backend', role: 'Validation', usage: 'API contracts, settings and schema-checked LLM output.' },
  sqlalchemy: { name: 'SQLAlchemy 2', category: 'backend', role: 'ORM', usage: 'Repositories and transactions over the application database.' },
  alembic: { name: 'Alembic', category: 'backend', role: 'Migrations', usage: 'Versioned schema migrations applied on startup.' },
  uvicorn: { name: 'Uvicorn', category: 'backend', role: 'ASGI server', usage: 'Serves the FastAPI application.' },
  httpx: { name: 'httpx2', category: 'backend', role: 'HTTP client', usage: 'Outbound calls to LLM endpoints and SPARQL services.' },

  rdflib: { name: 'RDFLib', category: 'semantics', role: 'RDF toolkit', usage: 'Parses and serialises Turtle, RDF/XML, JSON-LD and N-Triples.' },
  owlrl: { name: 'owlrl', category: 'semantics', role: 'OWL 2 RL reasoner', usage: 'Entailment preview and inconsistency detection on a copy of the ontology.' },
  pyshacl: { name: 'PySHACL', category: 'semantics', role: 'SHACL engine', usage: 'Validates generated, authored and preserved shapes without inference.' },
  pyoxigraph: { name: 'Oxigraph (pyoxigraph)', category: 'semantics', role: 'Embedded RDF store', usage: 'A built-in deployment target with SPARQL 1.1 support.' },

  openai: { name: 'OpenAI SDK', category: 'ai', role: 'LLM client', usage: 'OpenAI, Azure OpenAI and any OpenAI-compatible Chat Completions endpoint.' },
  anthropic: { name: 'Anthropic SDK', category: 'ai', role: 'LLM client', usage: 'Native Messages API with JSON-schema output.' },
  azure: { name: 'Azure Identity', category: 'ai', role: 'Authentication', usage: 'Microsoft Entra ID sign-in for Azure AI Foundry deployments.' },
  ollama: { name: 'Ollama', category: 'ai', role: 'Local models', usage: 'Fully local discovery and extraction; verified with qwen2.5:7b.' },
  pypdf: { name: 'pypdf', category: 'ai', role: 'PDF text extraction', usage: 'Reads page text from PDF sources for discovery and extraction.' },

  sqlite: { name: 'SQLite / PostgreSQL', category: 'stores', role: 'Application database', usage: 'SQLite by default; the models are PostgreSQL-compatible.' },
  sqlgraph: { name: 'Local SQL property graph', category: 'stores', role: 'Canonical graph store', usage: 'Gremlin-shaped, build-scoped and idempotent; the default graph target.' },
  neo4j: { name: 'Neo4j / AuraDB', category: 'stores', role: 'Property graph database', usage: 'Bolt / Cypher deployment target, verified live against AuraDB.' },
  cosmos: { name: 'Azure Cosmos DB for Gremlin', category: 'stores', role: 'Property graph database', usage: 'Gremlin deployment target (implemented, not yet live-verified).' },
  sparql: { name: 'SPARQL 1.1 endpoints', category: 'stores', role: 'RDF database protocol', usage: 'Deploys to GraphDB, Fuseki or any SPARQL 1.1 endpoint.' },

  pytest: { name: 'pytest', category: 'quality', role: 'Backend tests', usage: 'API, persistence, validation, governance, registry, KG pipeline and graph-store suites.' },
  ruff: { name: 'Ruff', category: 'quality', role: 'Python linter', usage: 'Fast linting of the backend code and tests.' },
  oxlint: { name: 'oxlint', category: 'quality', role: 'TypeScript linter', usage: 'Fast linting of the frontend code.' },
  playwright: { name: 'Playwright (playwright-core)', category: 'quality', role: 'Browser end-to-end journeys', usage: 'Scripted user journeys that drive a real browser against a running stack.' },
} as const satisfies Record<string, Technology>

export type TechId = keyof typeof TECHNOLOGIES

/* ------------------------------------------------------------------ architecture */

export type ArchLane = 'client' | 'backend' | 'infra'

export const ARCH_LANES: Record<ArchLane, { label: string }> = {
  client: { label: 'Browser · React SPA' },
  backend: { label: 'Backend · FastAPI modular monolith' },
  infra: { label: 'Storage & integrations' },
}

export interface ArchNode {
  id: string
  lane: ArchLane
  row: 0 | 1 | 2
  title: string
  subtitle: string
  icon: LucideIcon
  description: string
  responsibilities: readonly string[]
  technologies: readonly TechId[]
  link?: LabelledLink
}

export const ARCH_NODES: readonly ArchNode[] = [
  {
    id: 'shell',
    lane: 'client',
    row: 0,
    title: 'App shell & studios',
    subtitle: 'React · Vite · Tailwind',
    icon: Monitor,
    description:
      'A single-page application with four areas: Workspace, Ontology Studio, Knowledge Graph Studio and Settings. Every action calls a real API and nothing is simulated.',
    responsibilities: [
      'Project-scoped routing with ?tab= and ?build= deep links',
      'Server-state caching and polling of long-running work',
      'Accessible components built on Radix primitives',
      'Unsaved-changes guard for the designer',
    ],
    technologies: ['react', 'typescript', 'vite', 'tailwind', 'shadcn', 'tanstack', 'router'],
    link: { area: 'workspace', label: 'Open the Workspace' },
  },
  {
    id: 'designer',
    lane: 'client',
    row: 1,
    title: 'Ontology Designer',
    subtitle: 'React Flow canvas',
    icon: PencilRuler,
    description:
      'A node-and-edge canvas: classes are nodes and relationships are floating edges. Drag to connect, then refine in the inspectors. The lifecycle navigator and this map use the same engine.',
    responsibilities: [
      'Custom class nodes with OWL badges for equivalence, disjointness, restrictions and locked IRIs',
      'Floating, labelled edges with inverse markers',
      'Persisted layout and optimistic-locking saves',
    ],
    technologies: ['reactflow'],
    link: { area: 'ontology', tab: 'designer', label: 'Open the Designer' },
  },
  {
    id: 'explorer',
    lane: 'client',
    row: 2,
    title: 'Graph Explorer',
    subtitle: 'Cytoscape.js canvas',
    icon: Share2,
    description:
      'Renders the persisted knowledge graph with search, class, relationship and source filters, and a drawer that shows the provenance of every node and edge. It is loaded on demand.',
    responsibilities: [
      'Directed, labelled, colour-coded graph with layouts and fit',
      'Reads from the canonical graph or any verified deployment',
      'Source records and quotes highlighted in the provenance drawer',
    ],
    technologies: ['cytoscape'],
    link: { area: 'knowledge-graph', tab: 'explorer', label: 'Open the Explorer' },
  },
  {
    id: 'governance',
    lane: 'backend',
    row: 0,
    title: 'Ontology & governance',
    subtitle: 'Drafts · discovery · review · registry',
    icon: Boxes,
    description:
      'The canonical ontology model and the governed workflow around it: drafts, validation, AI discovery with alignment, SME decisions, publication and the lifecycle navigator.',
    responsibilities: [
      'Schema-only canonical model with stable ids and persisted IRIs',
      'Evidence-grounded discovery proposals with deterministic alignment',
      'Validation-gated publication of immutable versions',
      'Append-only activity trail',
    ],
    technologies: ['python', 'fastapi', 'uvicorn', 'pydantic', 'sqlalchemy', 'pypdf'],
    link: { area: 'ontology', tab: 'review', label: 'Open SME Review' },
  },
  {
    id: 'semantics',
    lane: 'backend',
    row: 1,
    title: 'Semantics & SHACL',
    subtitle: 'RDFLib · owlrl · PySHACL',
    icon: FileCode,
    description:
      'Standards support: OWL export, lossless RDF import that preserves axioms the designer cannot model, an OWL 2 RL reasoning preview and SHACL shape generation, authoring and validation.',
    responsibilities: [
      'Turtle, RDF/XML, JSON-LD and N-Triples serialisation',
      'Conservative RDF interpretation with a no-loss check',
      'SHACL validation without inference, mapped back to facts',
    ],
    technologies: ['rdflib', 'owlrl', 'pyshacl'],
    link: { area: 'ontology', tab: 'semantics', label: 'Open RDF / OWL' },
  },
  {
    id: 'kg',
    lane: 'backend',
    row: 2,
    title: 'KG pipeline & projection',
    subtitle: 'Extract · validate · deploy',
    icon: Cable,
    description:
      'Turns sources into graphs: connectors, mappings, LLM extraction, entity resolution, three independent validation lanes, evaluation and feedback, and projections to RDF or property graphs.',
    responsibilities: [
      'Ten persisted build stages bound to one published version',
      'Accepted, rejected or quarantined facts with reasons',
      'Verified deployments with compatibility reports',
    ],
    technologies: ['pydantic', 'pyshacl', 'pyoxigraph', 'httpx'],
    link: { area: 'knowledge-graph', tab: 'pipeline', label: 'Open the Pipeline' },
  },
  {
    id: 'db',
    lane: 'infra',
    row: 0,
    title: 'Application database',
    subtitle: 'SQLite · PostgreSQL-ready',
    icon: Database,
    description:
      'Drafts, proposals, builds, facts and the audit trail live in a relational database, with a write-once artifact store for published packages. Migrations run on startup.',
    responsibilities: [
      'Versioned Alembic migrations with immutability triggers',
      'Write-once artifacts with checksums',
      'Optimistic concurrency on drafts',
    ],
    technologies: ['sqlite', 'sqlalchemy', 'alembic'],
  },
  {
    id: 'llm',
    lane: 'infra',
    row: 1,
    title: 'LLM providers',
    subtitle: 'OpenAI · Anthropic · Azure · Ollama',
    icon: Bot,
    description:
      'Provider adapters hide each vendor SDK behind one protocol. Structured output is validated against a schema, and API keys are referenced by environment-variable name only.',
    responsibilities: [
      'Registered and tested from Settings, selectable per run',
      'Schema-validated output with bounded repair attempts',
      'Fully local operation with Ollama',
    ],
    technologies: ['openai', 'anthropic', 'azure', 'ollama'],
    link: { area: 'settings', label: 'Open Settings' },
  },
  {
    id: 'graphdb',
    lane: 'infra',
    row: 2,
    title: 'Graph databases',
    subtitle: 'SQL · Oxigraph · Neo4j · Cosmos · SPARQL',
    icon: Network,
    description:
      'The local SQL graph is canonical. Builds can also be deployed to embedded Oxigraph, SPARQL 1.1 endpoints (GraphDB, Fuseki), Neo4j / AuraDB and Cosmos DB for Gremlin, and read back into the explorer.',
    responsibilities: [
      'Provider catalogue with capability profiles',
      'Deployments verified by reading counts back',
      'Network-safety checks on every outbound connection',
    ],
    technologies: ['sqlgraph', 'pyoxigraph', 'neo4j', 'cosmos', 'sparql'],
    link: { area: 'knowledge-graph', tab: 'deployments', label: 'Open Deployments' },
  },
]

export type Side = 'Left' | 'Right' | 'Top' | 'Bottom'

export interface ArchEdge {
  source: string
  target: string
  from: Side
  to: Side
  label?: string
}

export const ARCH_EDGES: readonly ArchEdge[] = [
  { source: 'shell', target: 'governance', from: 'Right', to: 'Left', label: 'REST · JSON' },
  { source: 'designer', target: 'governance', from: 'Right', to: 'Left' },
  { source: 'explorer', target: 'kg', from: 'Right', to: 'Left', label: 'graph queries' },
  { source: 'governance', target: 'semantics', from: 'Bottom', to: 'Top', label: 'OWL · SHACL' },
  { source: 'semantics', target: 'kg', from: 'Bottom', to: 'Top', label: 'shapes · policies' },
  { source: 'governance', target: 'db', from: 'Right', to: 'Left' },
  { source: 'governance', target: 'llm', from: 'Right', to: 'Left', label: 'discovery' },
  { source: 'kg', target: 'llm', from: 'Right', to: 'Left', label: 'extraction' },
  { source: 'kg', target: 'graphdb', from: 'Right', to: 'Left', label: 'deploy · read back' },
]
