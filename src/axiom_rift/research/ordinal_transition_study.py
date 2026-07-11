"""Writer-gated evidence Job for causal ordinal transitions."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any,Mapping
import numpy as np
import pandas as pd
import scipy
from axiom_rift.core.canonical import canonical_bytes,parse_canonical
from axiom_rift.operations.writer import RunningJobExecution,StateWriter
from axiom_rift.operations import writer as writer_module
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,discovery_implementation_sha256
from axiom_rift.research.ordinal_transition_discovery import compute_registered_ordinal_surface,executable_configuration_map,loader_implementation_sha256,ordinal_implementation_sha256,project_ordinal_evaluation
from axiom_rift.research.trend_study import CRITERIA,EVIDENCE_MODES,PLANNED_CLAIMS,_claim_metrics,planned_verdict
from axiom_rift.research.validation import SCIENTIFIC_DISCOVERY_VALIDATOR_ID,SCIENTIFIC_MEASUREMENT_SCHEMA,SCIENTIFIC_RESULT_SCHEMA,build_validation_plan
MISSION_ID="MIS-0004";STUDY_ID="STU-0043";CALLABLE_IDENTITY="axiom_rift.research.ordinal_transition_study.execute_ordinal_job.v2";EVIDENCE_DEPTH="discovery"
def build_ordinal_validation_plan(eid:str)->dict[str,object]:return build_validation_plan(mission_id=MISSION_ID,executable_id=eid,evidence_depth=EVIDENCE_DEPTH,planned_claims=PLANNED_CLAIMS,evidence_modes=EVIDENCE_MODES,criteria=CRITERIA,candidate_eligible_on_pass=False)
def output_names(eid:str)->dict[str,str]:
    p=f"scientific/{STUDY_ID}/{eid.removeprefix('executable:')[:16]}";return {"context":f"{p}/evaluation.json","environment":f"{p}/environment.json","measurement":f"{p}/measurement.json","plan":f"{p}/validation-plan.json","result":f"{p}/result.json"}
def surface_output_name()->str:return f"scientific/{STUDY_ID}/ordinal-surface.json"
def surface_manifest_output_name()->str:return f"scientific/{STUDY_ID}/ordinal-surface-manifest.json"
def build_environment_manifest()->dict[str,object]:
    v={"ordinal_implementation_sha256":ordinal_implementation_sha256(),"dataset_sha256":DATASET_SHA256,"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"numpy_version":np.__version__,"pandas_version":pd.__version__,"python_version":".".join(str(x) for x in sys.version_info[:3]),"runner_implementation_sha256":sha256(Path(__file__).resolve().read_bytes()).hexdigest(),"schema":"scientific_engine_environment.v1","scipy_version":scipy.__version__,"shared_discovery_implementation_sha256":discovery_implementation_sha256(),"split_artifact_sha256":ROLLING_SPLIT_SHA256,"validator_id":SCIENTIFIC_DISCOVERY_VALIDATOR_ID,"writer_implementation_sha256":sha256(Path(writer_module.__file__).resolve().read_bytes()).hexdigest()};canonical_bytes(v);return v
def build_measurement(*,executable_id:str,job_id:str,job_hash:str,evaluation_artifact_hash:str,evaluation:Mapping[str,Any])->dict[str,object]:
    v={"claims":list(PLANNED_CLAIMS),"evidence_depth":EVIDENCE_DEPTH,"evidence_modes":list(EVIDENCE_MODES),"evaluation_artifact_hash":evaluation_artifact_hash,"executable_id":executable_id,"job_hash":job_hash,"job_id":job_id,"metrics":_claim_metrics(evaluation),"mission_id":MISSION_ID,"schema":SCIENTIFIC_MEASUREMENT_SCHEMA};canonical_bytes(v);return v
def build_result_manifest(*,executable_id:str,job_id:str,job_hash:str,measurement_artifact_hash:str)->dict[str,object]:
    v={"evidence_depth":EVIDENCE_DEPTH,"executable_id":executable_id,"job_hash":job_hash,"job_id":job_id,"mission_id":MISSION_ID,"observations":[{"claim_id":c,"measurement_artifact_hash":measurement_artifact_hash} for c in PLANNED_CLAIMS],"schema":SCIENTIFIC_RESULT_SCHEMA};canonical_bytes(v);return v
@dataclass(frozen=True,slots=True)
class OrdinalJobPacket:
    output_manifest:tuple[tuple[str,str],...];verdict:str
    def outputs(self)->dict[str,str]:return dict(self.output_manifest)
def _load(w:StateWriter,hashes:tuple[str,...])->tuple[dict[str,Any],str,str]:
    s=None;m=None
    for h in hashes:
        try:a=w.evidence.verify(h);v=parse_canonical((w.evidence._root/a.relative_path).read_bytes())
        except (FileNotFoundError,OSError,RuntimeError,ValueError):continue
        if isinstance(v,dict) and v.get("schema")=="ordinal_transition_surface.v2":s=(v,h)
        if isinstance(v,dict) and v.get("schema")=="ordinal_surface_manifest.v1":m=(v,h)
    if s is None or m is None or m[0].get("surface_artifact_hash")!=s[1]:raise ValueError("surface missing")
    return s[0],s[1],m[1]
def execute_ordinal_job(*,repository_root:str|Path,execution:RunningJobExecution)->OrdinalJobPacket:
    root=Path(repository_root).resolve();w=StateWriter(root);binding=w.verify_running_job_execution(execution,expected_callable_identity=CALLABLE_IDENTITY);spec=binding["spec"];subject=spec.get("evidence_subject")
    if binding.get("mission_id")!=MISSION_ID or binding.get("study_id")!=STUDY_ID or not isinstance(subject,dict) or subject.get("id") not in executable_configuration_map():raise ValueError("binding invalid")
    eid=subject["id"];plan=build_ordinal_validation_plan(eid);env=build_environment_manifest();ph=sha256(canonical_bytes(plan)).hexdigest();names=output_names(eid);inputs=tuple(spec["input_hashes"]);required={DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,ph,ordinal_implementation_sha256(),loader_implementation_sha256(),discovery_implementation_sha256()}
    if not required.issubset(inputs):raise ValueError("inputs missing")
    expected=set(spec["expected_outputs"]);produces=surface_output_name() in expected
    if produces:
        surface=compute_registered_ordinal_surface(root);sh=w.evidence.finalize(canonical_bytes(surface)).sha256;mh=w.evidence.finalize(canonical_bytes({"schema":"ordinal_surface_manifest.v1","surface_artifact_hash":sh,"surface_implementation_sha256":ordinal_implementation_sha256()})).sha256
    else:surface,sh,mh=_load(w,inputs)
    evaluation=project_ordinal_evaluation(surface,job_execution={**execution.payload(),"identity":execution.identity},subject_executable_id=eid,surface_artifact_hash=sh,surface_manifest_hash=mh);eh=w.evidence.finalize(canonical_bytes(evaluation)).sha256;measurement=build_measurement(executable_id=eid,job_id=execution.job_id,job_hash=execution.job_hash,evaluation_artifact_hash=eh,evaluation=evaluation);meash=w.evidence.finalize(canonical_bytes(measurement)).sha256;result=build_result_manifest(executable_id=eid,job_id=execution.job_id,job_hash=execution.job_hash,measurement_artifact_hash=meash);outputs={names["context"]:eh,names["environment"]:w.evidence.finalize(canonical_bytes(env)).sha256,names["measurement"]:meash,names["plan"]:w.evidence.finalize(canonical_bytes(plan)).sha256,names["result"]:w.evidence.finalize(canonical_bytes(result)).sha256}
    if produces:outputs[surface_output_name()]=sh;outputs[surface_manifest_output_name()]=mh
    return OrdinalJobPacket(output_manifest=tuple(sorted(outputs.items())),verdict=planned_verdict(plan,measurement))
__all__=["CALLABLE_IDENTITY","EVIDENCE_DEPTH","EVIDENCE_MODES","PLANNED_CLAIMS","STUDY_ID","build_environment_manifest","build_ordinal_validation_plan","execute_ordinal_job","output_names","surface_manifest_output_name","surface_output_name"]
