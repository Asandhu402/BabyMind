"""Canonical catalogue of exactly 50 BabyMind role agents."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    name: str
    domain: str
    purpose: str


_AGENT_ROWS = (
    ("Coordinator", "core", "Break down requests and coordinate specialist agents."),
    ("Researcher", "research", "Plan research and organize evidence."),
    ("FactChecker", "research", "Check claims against supplied evidence."),
    ("WebAnalyst", "research", "Analyze retrieved web material."),
    ("DocumentAnalyst", "knowledge", "Extract and organize document information."),
    ("Summarizer", "knowledge", "Produce concise summaries."),
    ("KnowledgeCurator", "knowledge", "Organize reusable knowledge."),
    ("MemoryManager", "memory", "Manage approved memory operations."),
    ("PrivacyGuard", "safety", "Review privacy risks and data minimization."),
    ("SecurityAuditor", "safety", "Review security-sensitive designs."),
    ("CodeArchitect", "development", "Design software architecture."),
    ("PythonDeveloper", "development", "Implement Python components."),
    ("FrontendDeveloper", "development", "Design user-interface components."),
    ("MobileDeveloper", "development", "Plan mobile application components."),
    ("TestEngineer", "development", "Design and run software tests."),
    ("DebuggingSpecialist", "development", "Diagnose software failures."),
    ("DevOpsEngineer", "development", "Plan builds and deployment."),
    ("DatabaseEngineer", "development", "Design data storage and schemas."),
    ("APIEngineer", "development", "Design and integrate APIs."),
    ("PerformanceEngineer", "development", "Analyze performance and resource use."),
    ("HindiLanguage", "language", "Assist with Hindi language tasks."),
    ("SanskritLanguage", "language", "Assist with Sanskrit language tasks."),
    ("PunjabiLanguage", "language", "Assist with Punjabi language tasks."),
    ("Translator", "language", "Translate while preserving meaning and context."),
    ("WritingEditor", "content", "Draft and edit written content."),
    ("CreativeWriter", "content", "Support original creative writing."),
    ("LearningCoach", "education", "Break learning goals into practical lessons."),
    ("Tutor", "education", "Explain concepts and create practice questions."),
    ("MathAnalyst", "analysis", "Work through mathematical problems."),
    ("DataAnalyst", "analysis", "Analyze structured data."),
    ("VisualizationAnalyst", "analysis", "Recommend clear data visualizations."),
    ("Planner", "productivity", "Turn goals into actionable plans."),
    ("TaskManager", "productivity", "Organize tasks and dependencies."),
    ("CalendarAssistant", "productivity", "Help plan schedules and time blocks."),
    ("EmailAssistant", "productivity", "Draft and organize email workflows."),
    ("TravelPlanner", "lifestyle", "Plan trips and compare travel options."),
    ("ShoppingResearcher", "lifestyle", "Compare products against requirements."),
    ("CareerAdvisor", "career", "Support career planning and applications."),
    ("ResumeSpecialist", "career", "Improve resumes and application materials."),
    ("InterviewCoach", "career", "Prepare interview practice and feedback."),
    ("FinanceEducator", "finance", "Explain financial concepts and trade-offs."),
    ("MarketResearcher", "finance", "Organize market research and risks."),
    ("TradingResearcher", "finance", "Analyze trading ideas without placing trades."),
    ("MusicAssistant", "creative", "Support songwriting and music workflows."),
    ("AudioAssistant", "creative", "Plan audio recording and editing workflows."),
    ("ImageWorkflow", "creative", "Plan image-generation workflows."),
    ("AutomationEngineer", "automation", "Design safe repeatable automations."),
    ("IntegrationEngineer", "automation", "Plan external service integrations."),
    ("QualityReviewer", "quality", "Review outputs for completeness and clarity."),
    ("ComplianceReviewer", "safety", "Flag policy and compliance considerations."),
    ("SessionReporter", "core", "Produce clear task status and hand-off reports."),
)

AGENTS: tuple[AgentSpec, ...] = tuple(
    AgentSpec(
        agent_id=f"BM-{index:02d}",
        name=name,
        domain=domain,
        purpose=purpose,
    )
    for index, (name, domain, purpose) in enumerate(_AGENT_ROWS, start=1)
)


def validate_registry(agents: tuple[AgentSpec, ...] = AGENTS) -> None:
    """Raise ValueError unless the registry contains exactly 50 unique agents."""
    if len(agents) != 50:
        raise ValueError(f"BabyMind requires exactly 50 agents; found {len(agents)}.")
    ids = [agent.agent_id for agent in agents]
    if len(set(ids)) != len(ids):
        raise ValueError("Agent IDs must be unique.")
    expected = [f"BM-{number:02d}" for number in range(1, 51)]
    if sorted(ids) != expected:
        raise ValueError("Agent IDs must be the continuous sequence BM-01 through BM-50.")


validate_registry()
