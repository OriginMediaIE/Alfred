"""Owner-isolated relationship, personal administration, and travel records."""

from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base
from src.schema_migrations import Migration, run_migrations

LifeBase = declarative_base()
def utcnow(): return datetime.now(timezone.utc)


class RelationshipProfile(LifeBase):
    __tablename__ = "relationship_profiles"
    id=Column(String(36),primary_key=True);owner=Column(String(255),nullable=False,index=True);contact_uid=Column(String(255),nullable=True,index=True)
    name=Column(String(500),nullable=False);organization=Column(String(500),nullable=False,default="");role=Column(String(500),nullable=False,default="")
    contact_methods_json=Column(Text,nullable=False,default="[]");last_interaction_at=Column(DateTime(timezone=True),nullable=True);upcoming_meetings_json=Column(Text,nullable=False,default="[]")
    commitments_json=Column(Text,nullable=False,default="[]");documents_json=Column(Text,nullable=False,default="[]");notes=Column(Text,nullable=False,default="")
    important_dates_json=Column(Text,nullable=False,default="[]");communication_style=Column(Text,nullable=False,default="");follow_up_status=Column(String(60),nullable=False,default="none")
    user_approved=Column(Boolean,nullable=False,default=False);created_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);updated_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);revision=Column(Integer,nullable=False,default=1)
    __table_args__=(Index("ix_relationship_owner_followup","owner","follow_up_status"),)


class PersonalAdminRecord(LifeBase):
    __tablename__="personal_admin_records"
    id=Column(String(36),primary_key=True);owner=Column(String(255),nullable=False,index=True);category=Column(String(60),nullable=False,index=True);title=Column(String(500),nullable=False)
    details_json=Column(Text,nullable=False,default="{}");due_at=Column(DateTime(timezone=True),nullable=True,index=True);renewal_at=Column(DateTime(timezone=True),nullable=True,index=True);recurrence_json=Column(Text,nullable=False,default="{}")
    sensitive=Column(Boolean,nullable=False,default=False);financial_opt_in=Column(Boolean,nullable=False,default=False);status=Column(String(60),nullable=False,default="active",index=True)
    created_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);updated_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);revision=Column(Integer,nullable=False,default=1)
    __table_args__=(Index("ix_admin_owner_due","owner","status","due_at"),)


class Trip(LifeBase):
    __tablename__="life_trips"
    id=Column(String(36),primary_key=True);owner=Column(String(255),nullable=False,index=True);title=Column(String(500),nullable=False);destination=Column(String(500),nullable=False,default="")
    starts_at=Column(DateTime(timezone=True),nullable=True,index=True);ends_at=Column(DateTime(timezone=True),nullable=True);origin_timezone=Column(String(100),nullable=False,default="UTC");destination_timezone=Column(String(100),nullable=False,default="UTC")
    status=Column(String(60),nullable=False,default="planning",index=True);notes=Column(Text,nullable=False,default="");created_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);updated_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);revision=Column(Integer,nullable=False,default=1)
    __table_args__=(Index("ix_trip_owner_start","owner","starts_at"),)


class TravelItem(LifeBase):
    __tablename__="travel_items"
    id=Column(String(36),primary_key=True);owner=Column(String(255),nullable=False,index=True);trip_id=Column(String(36),nullable=False,index=True);item_type=Column(String(60),nullable=False,index=True);title=Column(String(500),nullable=False)
    details_json=Column(Text,nullable=False,default="{}");starts_at=Column(DateTime(timezone=True),nullable=True);ends_at=Column(DateTime(timezone=True),nullable=True);status=Column(String(60),nullable=False,default="planned")
    sensitive=Column(Boolean,nullable=False,default=False);created_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);updated_at=Column(DateTime(timezone=True),nullable=False,default=utcnow);revision=Column(Integer,nullable=False,default=1)
    __table_args__=(Index("ix_travel_item_trip_type","trip_id","item_type"),)


def ensure_life_schema(engine):
    return run_migrations(engine,"personal_life",(Migration(1,"create_personal_life_domain",lambda bind: LifeBase.metadata.create_all(bind=bind)),))
