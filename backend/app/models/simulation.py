"""Simulation runs and everything they produce: knowledge graph, agents, posts, actions, event log,
reports, chats, surveys and real-world performance reports for calibration."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigID, IdMixin, TimestampMixin, UTCDateTime, utcnow

# draft -> building_graph -> graph_ready -> preparing -> ready -> queued -> running <-> paused
#       -> completed | failed | cancelled ; report_status tracks step 4 separately
SIM_STATUSES = ("draft", "building_graph", "graph_ready", "preparing", "ready", "queued", "running", "paused",
                "completed", "failed", "cancelled")


class Simulation(IdMixin, TimestampMixin, Base):
    __tablename__ = "simulations"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), default="Untitled simulation")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    step: Mapped[int] = mapped_column(Integer, default=1)
    requirement: Mapped[str] = mapped_column(Text, default="")        # the question the user wants answered
    content: Mapped[dict] = mapped_column(default=dict)                # type, title, platform, text, transcript, asset ids, variant_b
    audience: Mapped[dict] = mapped_column(default=dict)
    publish_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ontology: Mapped[dict] = mapped_column(default=dict)
    card: Mapped[dict] = mapped_column(default=dict)                   # content card (A) ; card_b inside content
    config: Mapped[dict] = mapped_column(default=dict)                 # generated + user-edited simulation config
    progress: Mapped[dict] = mapped_column(default=dict)               # live counters for list views
    results: Mapped[dict] = mapped_column(default=dict)
    usage: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    credits_estimate: Mapped[int] = mapped_column(Integer, default=0)
    credits_charged: Mapped[int] = mapped_column(Integer, default=0)
    report_status: Mapped[str] = mapped_column(String(24), default="none")   # none | queued | running | done | failed
    job_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    parent_id: Mapped[str | None] = mapped_column(String(32), index=True)       # the run this one re-tests (version history)
    template_id: Mapped[str | None] = mapped_column(String(32), index=True)     # audience template it was built from
    review_status: Mapped[str] = mapped_column(String(24), default="none")      # none | in_review | approved | changes_requested
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # denormalised at completion for cross-workspace benchmarks (anonymous aggregates only)
    score: Mapped[float | None] = mapped_column(Float, index=True)
    niche: Mapped[str | None] = mapped_column(String(40), index=True)          # dominant topic of the content
    rerun_every_days: Mapped[int | None] = mapped_column(Integer)              # recurring trend re-simulation
    next_rerun_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (Index("ix_graph_nodes_sim_key", "simulation_id", "key", unique=True),)
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(160))                     # stable id within the simulation
    kind: Mapped[str] = mapped_column(String(24))                     # entity | agent | post | signal | content | region
    type: Mapped[str] = mapped_column(String(80), default="")        # ontology entity type, agent kind, platform ...
    label: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict] = mapped_column(default=dict)
    round: Mapped[int] = mapped_column(Integer, default=-1)          # -1 = graph build, 0.. = simulation round
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    src: Mapped[str] = mapped_column(String(160))
    dst: Mapped[str] = mapped_column(String(160))
    relation: Mapped[str] = mapped_column(String(80))
    fact: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    round: Mapped[int] = mapped_column(Integer, default=-1)
    attributes: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SimAgent(Base):
    """LLM-driven agents (voice + stakeholder). Crowd agents live only in the worker (vectorised)."""
    __tablename__ = "sim_agents"
    __table_args__ = (Index("ix_sim_agents_sim_ref", "simulation_id", "ref", unique=True),)
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(64))                      # "p:<population idx>" or "s:<slug>"
    kind: Mapped[str] = mapped_column(String(16))                     # voice | stakeholder
    name: Mapped[str] = mapped_column(String(200))
    handle: Mapped[str] = mapped_column(String(80))
    region: Mapped[str] = mapped_column(String(8), default="")
    persona: Mapped[dict] = mapped_column(default=dict)
    config: Mapped[dict] = mapped_column(default=dict)                # activity, active hours, stance, influence ...
    reaction: Mapped[dict] = mapped_column(default=dict)              # first-exposure reaction (round 0)
    state: Mapped[dict] = mapped_column(default=dict)                 # opinion trajectory, memory, counters
    followers: Mapped[int] = mapped_column(Integer, default=0)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(12))                 # feed | forum
    kind: Mapped[str] = mapped_column(String(12), default="post")     # post | comment | quote | repost | external | event
    author_ref: Mapped[str] = mapped_column(String(64))               # agent ref, "creator", "ext:<source>", "event"
    author_name: Mapped[str] = mapped_column(String(200), default="")
    parent_id: Mapped[int | None] = mapped_column(BigID)
    root_id: Mapped[int | None] = mapped_column(BigID)
    variant: Mapped[str] = mapped_column(String(2), default="A")
    content: Mapped[str] = mapped_column(Text, default="")
    round: Mapped[int] = mapped_column(Integer, default=0)
    sim_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    stats: Mapped[dict] = mapped_column(default=dict)                 # likes, reposts, comments, up, down, views, crowd_*
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    source_url: Mapped[str | None] = mapped_column(String(800))


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (Index("ix_actions_sim_round", "simulation_id", "round"),)
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"))
    round: Mapped[int] = mapped_column(Integer)
    sim_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    platform: Mapped[str] = mapped_column(String(12))
    actor_ref: Mapped[str] = mapped_column(String(64))
    actor_name: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(24))
    post_id: Mapped[int | None] = mapped_column(BigID)
    target_post_id: Mapped[int | None] = mapped_column(BigID)
    target_ref: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(default=dict)


class SimEvent(Base):
    """Append-only event log; the live stream and replays are both served from it."""
    __tablename__ = "sim_events"
    __table_args__ = (Index("ix_sim_events_sim_seq", "simulation_id", "seq", unique=True),)
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Report(IdMixin, TimestampMixin, Base):
    __tablename__ = "reports"
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    title: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    outline: Mapped[list] = mapped_column(default=list)
    sections: Mapped[list] = mapped_column(default=list)              # [{title, content, tools_used}]
    markdown: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str | None] = mapped_column(Text)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_sim_target", "simulation_id", "target"),)
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"))
    target: Mapped[str] = mapped_column(String(80))                   # "report" | agent ref | "pop:<idx>"
    role: Mapped[str] = mapped_column(String(12))                     # user | assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(default=dict)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Survey(IdMixin, TimestampMixin, Base):
    __tablename__ = "surveys"
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="running")
    answers: Mapped[list] = mapped_column(default=list)
    summary: Mapped[str] = mapped_column(Text, default="")


class PerformanceReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "performance_reports"
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    variant: Mapped[str] = mapped_column(String(1), default="A", server_default="A")
    social_post_id: Mapped[str | None] = mapped_column(ForeignKey("social_posts.id", ondelete="SET NULL"), unique=True)
    views: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    ctr: Mapped[float | None] = mapped_column(Float)
    engagement_rate: Mapped[float | None] = mapped_column(Float)
    retention: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    reported_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
