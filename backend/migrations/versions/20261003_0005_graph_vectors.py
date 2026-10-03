"""Native graph embeddings using the existing local hashing/pgvector layer."""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    op.add_column("graph_nodes", sa.Column("vector", Vector(128) if pg else sa.JSON(), nullable=True))
    from app.services.datapool.retrieval import embed
    table = sa.table("graph_nodes", sa.column("id", sa.Integer()), sa.column("label", sa.Text()),
                     sa.column("summary", sa.Text()), sa.column("vector", Vector(128) if pg else sa.JSON()))
    last_id = 0
    while True:
        rows = op.get_bind().execute(sa.select(table.c.id, table.c.label, table.c.summary)
                                    .where(table.c.id > last_id).order_by(table.c.id).limit(500)).all()
        if not rows:
            break
        for row in rows:
            op.get_bind().execute(table.update().where(table.c.id == row.id)
                                 .values(vector=embed((row.label or "") + " " + (row.summary or "")).tolist()))
        last_id = rows[-1].id
    if pg:
        op.create_index("ix_graph_nodes_cosine", "graph_nodes", ["vector"], postgresql_using="hnsw",
                        postgresql_ops={"vector": "vector_cosine_ops"})


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_graph_nodes_cosine", table_name="graph_nodes")
    op.drop_column("graph_nodes", "vector")
