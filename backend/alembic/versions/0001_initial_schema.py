"""initial schema: users, documents, chunks (pgvector + tsvector), conversations, evaluation, usage

Revision ID: 0001
Revises:
Create Date: 2026-11-23

The embedding column dimension comes from EMBEDDING_DIMENSION at migration time.
Switching to an embedding model with a different dimension requires a new
migration and a full re-index (the application refuses to start on a mismatch).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dimension

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('hashed_password', sa.String(length=200), nullable=False),
    sa.Column('role', sa.Enum('user', 'admin', name='user_role'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('conversations',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations'))
    )
    op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'], unique=False)
    op.create_table('documents',
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=10), nullable=False),
    sa.Column('content_type', sa.String(length=120), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=False),
    sa.Column('status', sa.Enum('uploaded', 'processing', 'indexed', 'failed', name='document_status'), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('embedding_model', sa.String(length=200), nullable=True),
    sa.Column('chunking_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ingestion_ms', sa.Integer(), nullable=True),
    sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_documents_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('owner_id', 'sha256', name='uq_documents_owner_sha256')
    )
    op.create_index('ix_documents_owner_created', 'documents', ['owner_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_documents_owner_id'), 'documents', ['owner_id'], unique=False)
    op.create_index(op.f('ix_documents_status'), 'documents', ['status'], unique=False)
    op.create_table('evaluation_runs',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_evaluation_runs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluation_runs'))
    )
    op.create_index('ix_eval_runs_user_created', 'evaluation_runs', ['user_id', 'created_at'], unique=False)
    op.create_table('usage_events',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('event_type', sa.String(length=30), nullable=False),
    sa.Column('query', sa.Text(), nullable=True),
    sa.Column('latency_ms', sa.Float(), nullable=False),
    sa.Column('retrieval_ms', sa.Float(), nullable=True),
    sa.Column('llm_ms', sa.Float(), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.Column('cache_hit', sa.Boolean(), nullable=True),
    sa.Column('model', sa.String(length=200), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_usage_events_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_events'))
    )
    op.create_index('ix_usage_type_created', 'usage_events', ['event_type', 'created_at'], unique=False)
    op.create_index('ix_usage_user_created', 'usage_events', ['user_id', 'created_at'], unique=False)
    op.create_table('user_settings',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings'))
    )
    op.create_table('document_chunks',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('page_end', sa.Integer(), nullable=True),
    sa.Column('section', sa.String(length=500), nullable=True),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('char_start', sa.Integer(), nullable=False),
    sa.Column('char_end', sa.Integer(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=False),
    sa.Column('embedding_model', sa.String(length=200), nullable=False),
    sa.Column('content_tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', content)", persisted=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_chunks_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_document_chunks_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunks')),
    sa.UniqueConstraint('document_id', 'chunk_index', name='uq_chunks_document_index')
    )
    op.create_index('ix_chunks_content_tsv', 'document_chunks', ['content_tsv'], unique=False, postgresql_using='gin')
    op.create_index('ix_chunks_embedding_hnsw', 'document_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_chunks_owner_model', 'document_chunks', ['owner_id', 'embedding_model'], unique=False)
    op.create_index(op.f('ix_document_chunks_document_id'), 'document_chunks', ['document_id'], unique=False)
    op.create_table('messages',
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index('ix_messages_conversation_created', 'messages', ['conversation_id', 'created_at'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_messages_conversation_created', table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_document_chunks_document_id'), table_name='document_chunks')
    op.drop_index('ix_chunks_owner_model', table_name='document_chunks')
    op.drop_index('ix_chunks_embedding_hnsw', table_name='document_chunks', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index('ix_chunks_content_tsv', table_name='document_chunks', postgresql_using='gin')
    op.drop_table('document_chunks')
    op.drop_table('user_settings')
    op.drop_index('ix_usage_user_created', table_name='usage_events')
    op.drop_index('ix_usage_type_created', table_name='usage_events')
    op.drop_table('usage_events')
    op.drop_index('ix_eval_runs_user_created', table_name='evaluation_runs')
    op.drop_table('evaluation_runs')
    op.drop_index(op.f('ix_documents_status'), table_name='documents')
    op.drop_index(op.f('ix_documents_owner_id'), table_name='documents')
    op.drop_index('ix_documents_owner_created', table_name='documents')
    op.drop_table('documents')
    op.drop_index('ix_conversations_user_updated', table_name='conversations')
    op.drop_table('conversations')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    sa.Enum(name='document_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='user_role').drop(op.get_bind(), checkfirst=True)
