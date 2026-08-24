"""Validated CRUD for personal-life records; never performs purchases or bookings."""
import json, os, uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.constants import DATA_DIR
from src.life_models import RelationshipProfile, PersonalAdminRecord, Trip, TravelItem, ensure_life_schema

ADMIN_CATEGORIES={"renewal","subscription","bill","important_document","warranty","insurance","travel_document","property","vehicle","membership","household_maintenance","recurring_appointment"}
FINANCIAL_CATEGORIES={"bill","subscription","insurance"}
TRAVEL_ITEM_TYPES={"flight","accommodation","transfer","reservation","travel_document","calendar_event","packing_item","pre_travel_task","during_travel_briefing","post_travel_expense"}
MODELS={"relationship":RelationshipProfile,"admin":PersonalAdminRecord,"trip":Trip,"travel_item":TravelItem}
JSON_FIELDS={"contact_methods","upcoming_meetings","commitments","documents","important_dates","details","recurrence"}
DATE_FIELDS={"last_interaction_at","due_at","renewal_at","starts_at","ends_at"}
OWNER_NONE="__local__"
class LifeError(RuntimeError): code="life_error"
class LifeNotFound(LifeError): code="life_not_found"
class LifeConflict(LifeError): code="life_conflict"
class LifeValidationError(LifeError): code="invalid_life_record"
def _owner(owner): return str(owner).strip().lower() if owner else OWNER_NONE
def _dt(value):
    if value in (None,""): return None
    try:
        parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"));return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError as exc: raise LifeValidationError("Invalid ISO date/time") from exc
def _iso(value): return value.isoformat() if value else None
def _json(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))

class LifeService:
    def __init__(self,*,session_factory=None,database_url=None):
        if session_factory is None:
            url=database_url or os.getenv("OM_LIFE_DATABASE_URL") or f"sqlite:///{Path(DATA_DIR)/'personal_life.db'}";engine=create_engine(url,connect_args={"check_same_thread":False} if url.startswith("sqlite") else {});ensure_life_schema(engine);session_factory=sessionmaker(bind=engine,autocommit=False,autoflush=False)
        self.sessions=session_factory
    def _row(self,row,kind):
        out={column.name:getattr(row,column.name) for column in row.__table__.columns};out["kind"]=kind;out["owner"]=None if out["owner"]==OWNER_NONE else out["owner"]
        for field in list(out):
            if field.endswith("_json"): out[field[:-5]]=json.loads(out.pop(field) or "{}")
            elif isinstance(out[field],datetime): out[field]=_iso(out[field])
        return out
    def _owned(self,db,owner,kind,record_id):
        model=MODELS.get(kind)
        if not model: raise LifeValidationError("Unknown record kind")
        row=db.query(model).filter(model.id==str(record_id),model.owner==_owner(owner)).first()
        if not row: raise LifeNotFound("Personal-life record not found")
        return row
    def _validate_trip_link(self,db,owner,trip_id):
        trip_id=str(trip_id or "").strip()
        if not trip_id:
            raise LifeValidationError("travel_item requires trip_id")
        trip=db.query(Trip.id).filter(Trip.id==trip_id,Trip.owner==_owner(owner)).first()
        if not trip:
            raise LifeValidationError("trip_id does not identify one of the owner's trips")
        return trip_id
    def _values(self,kind,record,*,creating):
        if not isinstance(record,dict): raise LifeValidationError("record must be an object")
        allowed={c.name for c in MODELS[kind].__table__.columns}-{ "id","owner","created_at","updated_at","revision"}
        values={}
        for key,value in record.items():
            target=key+"_json" if key in JSON_FIELDS else key
            if target not in allowed: raise LifeValidationError(f"Unknown {kind} field: {key}")
            if key in JSON_FIELDS: values[target]=_json(value)
            elif key in DATE_FIELDS: values[key]=_dt(value)
            elif isinstance(value,str): values[key]=value.strip()[:20000]
            else: values[key]=value
        if creating and not str(values.get("title") or values.get("name") or "").strip(): raise LifeValidationError("name or title is required")
        if kind=="relationship" and creating and values.get("user_approved") is not True: raise LifeValidationError("Relationship profiles require explicit user approval")
        if kind=="admin":
            category=str(values.get("category") or "").lower()
            if creating and category not in ADMIN_CATEGORIES: raise LifeValidationError("Unsupported personal administration category")
            if category in FINANCIAL_CATEGORIES and (values.get("financial_opt_in") is not True or values.get("sensitive") is not True): raise LifeValidationError("Financial administration requires explicit opt-in and sensitive handling")
        if kind=="travel_item":
            if creating and str(values.get("item_type") or "") not in TRAVEL_ITEM_TYPES: raise LifeValidationError("Unsupported travel item type")
            details=record.get("details") or {}
            if any(key in details for key in ("purchase","book","payment_method","card_number")): raise LifeValidationError("Purchasing and booking instructions are not accepted")
        return values
    def create(self,owner,kind,record):
        if kind not in MODELS: raise LifeValidationError("Unknown record kind")
        values=self._values(kind,record,creating=True)
        with self.sessions() as db:
            if kind=="travel_item": values["trip_id"]=self._validate_trip_link(db,owner,values.get("trip_id"))
            row=MODELS[kind](id=str(uuid.uuid4()),owner=_owner(owner),**values);db.add(row);db.commit();db.refresh(row);return self._row(row,kind)
    def get(self,owner,kind,record_id):
        with self.sessions() as db:return self._row(self._owned(db,owner,kind,record_id),kind)
    def list(self,owner,kind,*,status=None,trip_id=None,limit=100):
        model=MODELS.get(kind)
        if not model: raise LifeValidationError("Unknown record kind")
        with self.sessions() as db:
            q=db.query(model).filter(model.owner==_owner(owner));
            if status and hasattr(model,"status"): q=q.filter(model.status==status)
            if trip_id and kind=="travel_item": q=q.filter(model.trip_id==trip_id)
            return [self._row(row,kind) for row in q.order_by(model.updated_at.desc()).limit(max(1,min(int(limit),500))).all()]
    def update(self,owner,kind,record_id,record,revision):
        with self.sessions() as db:
            row=self._owned(db,owner,kind,record_id)
            if row.revision!=int(revision): raise LifeConflict("Record changed; refresh and retry")
            values=self._values(kind,record,creating=False)
            if kind=="travel_item" and "trip_id" in values: values["trip_id"]=self._validate_trip_link(db,owner,values["trip_id"])
            for key,value in values.items(): setattr(row,key,value)
            row.revision+=1;row.updated_at=datetime.now(timezone.utc);db.commit();db.refresh(row);return self._row(row,kind)
    def delete(self,owner,kind,record_id,revision):
        with self.sessions() as db:
            row=self._owned(db,owner,kind,record_id)
            if row.revision!=int(revision): raise LifeConflict("Record changed; refresh and retry")
            if kind=="trip" and db.query(TravelItem).filter(TravelItem.owner==_owner(owner),TravelItem.trip_id==record_id).first(): raise LifeConflict("Delete trip items before deleting the trip")
            db.delete(row);db.commit();return {"ok":True,"id":record_id,"kind":kind}

_service=None
def get_life_service():
    global _service
    if _service is None:_service=LifeService()
    return _service
