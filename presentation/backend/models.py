from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
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
class Freshness(Model):
    id:str;title:str;state:Literal['fresh','info','warning','critical','unavailable']
    observed_at:str|None;age_seconds:int|None;note:str
class Talker(Model):
    ip:str;bytes:int
class Talkers(Model):
    state:Literal['available','unavailable','partial'];rows:list[Talker];note:str
class BlockRow(Model):
    interface:str;source:str;destination:str;destination_port:int|None;protocol:str;count:int
class Blocks(Model):
    state:Literal['available','unavailable','partial'];rows:list[BlockRow];unparsed:int;note:str
class DnsName(Model):
    name:str;queries:int
class DnsClient(Model):
    ip:str;name:str;queries:int
class DnsPanel(Model):
    state:Literal['available','unavailable','partial'];domains:list[DnsName];clients:list[DnsClient];note:str
class GatewayStatus(Model):
    state:Literal['up','down','unknown','unavailable'];observed_at:str|None;summary:str;sample:str
class OpsHome(Model):
    mode:Literal['demo','live'];illustrative:bool;as_of:str;window:Window;freshness:list[Freshness]
    talkers:Talkers;blocks:Blocks;dns:DnsPanel;gateway:GatewayStatus;notes:list[str]
class _Allowlist(Model):
    model_config=ConfigDict(extra='forbid',populate_by_name=True)
    id:str
    device_class:str=Field(alias='class')
    name:str;dns_names:list[str];ip:str;mac:str;notes:str=''
class DestinationName(Model):
    name:str;queries:int
class DestinationHost(_Allowlist):
    state:Literal['available','unavailable','partial']
    queries:int|None;first_seen:str|None;last_seen:str|None
    domains:list[DestinationName];sites:list[DestinationName];note:str
class DestinationsView(Model):
    mode:Literal['demo','live'];illustrative:bool;as_of:str;window:Window;deduped:bool
    inventory:list[_Allowlist];hosts:list[DestinationHost];notes:list[str]
