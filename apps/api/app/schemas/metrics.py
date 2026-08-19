from pydantic import BaseModel


class MetricsOut(BaseModel):
    profiles_total: int
    looks_total: int
    looks_by_status: dict[str, int]
    video_requests_total: int
    video_requests_by_status: dict[str, int]
    jobs_by_status: dict[str, int]
    jobs_by_type: dict[str, int]
