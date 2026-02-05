from typing import Dict, Any, List, Optional
from pydantic import BaseModel

class ChangeItem(BaseModel):
    id: int
    entity_type: str
    entity_id: Optional[str] = None
    action_type: str
    payload_json: Optional[str] = None
    created_at: Optional[str] = None

class SyncPushRequest(BaseModel):
    tenant_id: str
    station_id: Optional[str] = None
    changes: List[ChangeItem]

class SnapshotPayload(BaseModel):
    tenant_id: str
    station_id: Optional[str] = None
    teachers: List[Dict[str, Any]] = []
    students: List[Dict[str, Any]] = []
    static_messages: List[Dict[str, Any]] = []
    threshold_messages: List[Dict[str, Any]] = []
    news_items: List[Dict[str, Any]] = []
    ads_items: List[Dict[str, Any]] = []
    student_messages: List[Dict[str, Any]] = []

class Snapshot2Payload(BaseModel):
    tenant_id: str
    station_id: Optional[str] = None
    snapshot: Dict[str, Any] = {}

class StudentUpdatePayload(BaseModel):
    student_id: int
    points: Optional[int] = None
    private_message: Optional[str] = None
    card_number: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    class_name: Optional[str] = None
    id_number: Optional[str] = None
    serial_number: Optional[str] = None
    photo_number: Optional[str] = None
    is_free_fix_blocked: Optional[int] = None

class StudentSavePayload(BaseModel):
    student_id: Optional[int] = None
    first_name: str
    last_name: str
    class_name: Optional[str] = None
    card_number: Optional[str] = None
    serial_number: Optional[str] = None
    photo_number: Optional[str] = None
    id_number: Optional[str] = None
    points: Optional[int] = None
    private_message: Optional[str] = None
    is_free_fix_blocked: Optional[int] = None

class StudentDeletePayload(BaseModel):
    student_id: int

class StudentQuickUpdatePayload(BaseModel):
    operation: str
    points: int
    mode: str
    card_number: Optional[str] = None
    serial_from: Optional[int] = None
    serial_to: Optional[int] = None
    class_names: Optional[List[str]] = None
    student_ids: Optional[List[int]] = None

class StudentManualArrivalPayload(BaseModel):
    student_id: int
    date_str: str
    time_str: str

class TeacherSavePayload(BaseModel):
    teacher_id: Optional[int] = None
    name: Optional[str] = None
    card_number: Optional[str] = None
    card_number2: Optional[str] = None
    card_number3: Optional[str] = None
    is_admin: Optional[int] = None
    can_edit_student_card: Optional[int] = None
    can_edit_student_photo: Optional[int] = None
    bonus_max_points_per_student: Optional[int] = None
    bonus_max_total_runs: Optional[int] = None

class TeacherClassesPayload(BaseModel):
    teacher_id: int
    classes: List[str]

class TeacherDeletePayload(BaseModel):
    teacher_id: int

class LicenseFetchPayload(BaseModel):
    tenant_id: str
    api_key: Optional[str] = None
    password: Optional[str] = None
    system_code: str
    station_role: Optional[str] = None

class GenericSettingPayload(BaseModel):
    key: str
    value: Dict[str, Any]
