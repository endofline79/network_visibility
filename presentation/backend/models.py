from typing import Literal
from pydantic import BaseModel,ConfigDict
class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Source(Model):
    id:str;title:str;state:Literal['fresh','stale','unavailable','quiet','partial'];observed_at:str|None;note:str
class Window(Model):
    start:str;end:str;seconds:int;label:str
class Busiest(Model):
    name:str;ip:str;bytes:int;identity_note:str
class Metrics(Model):
    devices:int|None;infrastructure:int|None;router_bytes:int|None;capture_bytes:int|None
    dns_queries:int|None;dns_blocked:int|None;firewall_blocks:int|None;destinations:int|None;busiest:Busiest|None;attention:int
class Country(Model):
    code:str;name:str;count:int;percent:float;latitude:float|None;longitude:float|None
class AgeBucket(Model):
    last_seen:str;count:int
class Location(Model):
    id:str;country_code:str;country_name:str;region:str|None;cities:list[str];other_city_labels:int
    name:str;precision:Literal['area','country','unknown','overflow'];latitude:float|None;longitude:float|None;count:int
    last_seen:str|None;activity_id:str|None;age_buckets:list[AgeBucket]
    accuracy_radius_km:float|None;radius_known_count:int
class Device(Model):
    id:str;name:str;ip:str;type:str;attachment:str;observed_at:str
class Recent(Model):
    id:str;time:str;text:str;source:str
class Bin(Model):
    time:str;bytes:int
class Geo(Model):
    available:bool;provider:str;age_days:int|None
    build_utc:str|None=None;grid_degrees:float=.5;max_mapped_areas:int=96
    uncertainty_note:str='IP location estimates are approximate. Grouping size is not an accuracy guarantee.'
class Overview(Model):
    mode:Literal['demo','live'];as_of:str;window:Window;sources:list[Source];metrics:Metrics;countries:list[Country]
    locations:list[Location]=[]
    location_state:Literal['available','withheld','unavailable']='unavailable'
    devices:list[Device];recent:list[Recent];trend:list[Bin];coverage:list[str];issues:list[str];geo:Geo
class LiveCountry(Country):
    last_seen:str;activity_id:str
class Alert(Model):
    fingerprint:str;rule:str;severity:Literal['info','warning','critical'];state:Literal['firing','resolved']
    subject:str;summary:str;first_seen:str;last_seen:str;age_seconds:int;evidence_query:str
class Alerts(Model):
    mode:Literal['demo','live'];as_of:str;checker:Literal['ok','silent','unknown'];illustrative:bool
    open:list[Alert];resolved:list[Alert]
class GlobeSnapshot(Model):
    mode:Literal['demo','live'];as_of:str;window:Window;refresh_seconds:int
    state:Literal['fresh','stale','partial','unavailable'];observed_at:str|None
    endpoints:int|None;countries:list[LiveCountry];locations:list[Location]=[]
    geo:Geo;note:str
