#!/usr/bin/env python3
"""Normalize external TBProfiler JSON results into JLIGHT's bioRuns CSV schema."""
from __future__ import annotations
import argparse, csv, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COLUMNS = ["analysisType","outputType","status","qualityStatus","summary","createdAt","sourceSystem","sourceRecordId"]

def first_value(obj: Any, names: tuple[str,...]) -> Any:
    if not isinstance(obj, dict): return None
    for name in names:
        value=obj.get(name)
        if value not in (None,"",[]): return value
    return None

def number(value: Any) -> float | None:
    if isinstance(value,dict): value=first_value(value,("value","median","mean","percent"))
    if isinstance(value,bool) or value is None: return None
    try: return float(value.strip().replace("%","") if isinstance(value,str) else value)
    except (TypeError,ValueError): return None

def jsonable_text(value: Any) -> str | None:
    if value is None: return None
    return str(value) if isinstance(value,(str,int,float)) else json.dumps(value,ensure_ascii=False,sort_keys=True)

def compact_variant(v: Any) -> dict[str,Any]:
    if not isinstance(v,dict): return {"sourceValue":v}
    raw=v.get("annotation") or v.get("annotations") or []
    if isinstance(raw,dict): raw=[raw]
    annotations=[{"drug":first_value(i,("drug","antimicrobial","name")),"confidence":i.get("confidence"),"source":i.get("source"),"comment":i.get("comment")} for i in raw if isinstance(i,dict)] if isinstance(raw,list) else []
    drugs=v.get("drugs") or [i["drug"] for i in annotations if i.get("drug")]
    return {"gene":first_value(v,("gene_name","gene_id","gene","locus_tag")),"position":first_value(v,("pos","genome_pos","position")),"mutation":first_value(v,("protein_change","nucleotide_change","mutation")),"proteinChange":v.get("protein_change"),"nucleotideChange":v.get("nucleotide_change"),"type":first_value(v,("type","variant_type","consequence")),"frequency":number(first_value(v,("freq","frequency","allele_frequency"))),"depth":number(v.get("depth")),"drugs":drugs,"annotations":annotations}

def normalize_one(path: Path,dataset_accession: str,tool_version: str,db_version: str)->dict[str,str]:
    result=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result,dict): raise ValueError(f"{path.name}: TBProfiler result must be a JSON object")
    run_id=first_value(result,("id","sample","sample_id","run_id"))
    if not run_id: raise ValueError(f"{path.name}: no run/sample identifier in TBProfiler output")
    pipeline=result.get("pipeline") if isinstance(result.get("pipeline"),dict) else {}
    qc=result.get("qc") if isinstance(result.get("qc"),dict) else {}
    genome_coverage=number(first_value(qc,("genome_median_depth","median_coverage","median_depth","median_depth_of_coverage","coverage_median","coverage")))
    target_coverage=number(first_value(qc,("target_median_depth","median_target_depth")))
    median_coverage=target_coverage if target_coverage is not None else genome_coverage
    mapping_rate=number(first_value(qc,("percent_reads_mapped","percentage_reads_mapped","pct_reads_mapped","pct_mapped","mapping_rate","mapped_percent")))
    read_count=number(first_value(qc,("num_reads","number_of_reads","total_reads","reads")))
    mapped_reads=number(first_value(qc,("num_reads_mapped","reads_mapped","mapped_reads")))
    target_qc=qc.get("target_qc") if isinstance(qc.get("target_qc"),list) else []
    target_qc_summary=[{"target":x.get("target"),"medianDepth":number(x.get("median_depth")),"percentDepthPass":number(x.get("percent_depth_pass"))} for x in target_qc if isinstance(x,dict)]
    dr=result.get("dr_variants") or []; other=result.get("other_variants") or []
    if not isinstance(dr,list) or not isinstance(other,list): raise ValueError(f"{path.name}: variant collections must be arrays")
    warnings=[]
    if median_coverage is not None and median_coverage<30:
        warnings.append(f"Median target coverage {median_coverage:g}x is below the 30x review threshold; some mutations may not be detected.")
        quality="review_required_low_coverage"
    elif median_coverage is None:
        warnings.append("Median target/genome coverage was not present in the imported QC fields.")
        quality="qc_not_reported"
    else: quality="qc_reported"
    pv=first_value(pipeline,("software_version","version","pipeline_version")) or first_value(result,("pipeline_version","tb_profiler_version","tb-profiler-version","version")) or tool_version or os.environ.get("TBPROFILER_VERSION")
    embedded_db=first_value(pipeline,("db_version","database_version","tbdb_version")) or first_value(result,("db_version","database_version","tbdb"))
    if isinstance(embedded_db,dict): embedded_db=first_value(embedded_db,("commit","revision","sha","version"))
    # The pinned workflow argument is the authoritative full immutable commit.
    # TBProfiler metadata may contain only an abbreviated Git SHA.
    verified_db=db_version if db_version and db_version!="not_reported" else embedded_db
    if isinstance(pv,dict): pv=first_value(pv,("version","release","tag"))
    if isinstance(pv,str): pv=pv.strip()
    if isinstance(verified_db,str): verified_db=verified_db.strip()
    if not pv: raise ValueError(f"{path.name}: TBProfiler version missing; pass the verified installed version")
    if not verified_db: raise ValueError(f"{path.name}: TB database revision missing; pass the verified database commit")
    if embedded_db and verified_db and not str(verified_db).startswith(str(embedded_db)):
        raise ValueError(f"{path.name}: embedded TB database revision does not match the pinned database commit")
    db=verified_db
    date=first_value(result,("date","created_at","timestamp"))
    summary={"datasetAccession":dataset_accession,"runAccession":str(run_id),"pipeline":"TBProfiler","pipelineVersion":jsonable_text(pv),"databaseVersion":jsonable_text(db),"lineage":jsonable_text(result.get("lineage")),"mainLineage":jsonable_text(first_value(result,("main_lineage","mainLineage"))),"subLineage":jsonable_text(first_value(result,("sub_lineage","subLineage"))),"spoligotype":jsonable_text(result.get("spoligotype")),"drugResistanceType":jsonable_text(first_value(result,("drtype","drug_resistance","drug-resistance"))),"medianCoverage":median_coverage,"genomeMedianCoverage":genome_coverage,"targetMedianCoverage":target_coverage,"mappingRatePercent":mapping_rate,"readCount":read_count,"mappedReadCount":mapped_reads,"targetQc":target_qc_summary,"resistanceVariantCount":len(dr),"resistanceVariants":[compact_variant(x) for x in dr],"otherVariantCount":len(other),"otherVariants":[compact_variant(x) for x in other],"qcWarnings":warnings,"sourceResultFile":path.name,"sourceUrl":f"https://tbdr.lshtm.ac.uk/results/{run_id}","sourceDate":jsonable_text(date),"interpretationLimit":"External genotypic prediction only; not phenotypic DST or a clinical diagnosis."}
    return {"analysisType":"Mycobacterium tuberculosis WGS","outputType":"TBProfiler JSON summary","status":"completed","qualityStatus":quality,"summary":json.dumps(summary,ensure_ascii=False,sort_keys=True),"createdAt":jsonable_text(date) or datetime.now(timezone.utc).isoformat(),"sourceSystem":"TBProfiler","sourceRecordId":str(run_id)}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--results-dir",required=True,type=Path); p.add_argument("--dataset-accession",required=True); p.add_argument("--tool-version",default=os.environ.get("TBPROFILER_VERSION","not_reported")); p.add_argument("--db-version",default=os.environ.get("TBPROFILER_DB_VERSION","not_reported")); p.add_argument("--output",required=True,type=Path); a=p.parse_args()
    paths=sorted(a.results_dir.glob("*.results.json"))
    if not paths: raise SystemExit(f"No *.results.json files found in {a.results_dir}")
    rows=[normalize_one(x,a.dataset_accession,a.tool_version,a.db_version) for x in paths]
    ids=[x["sourceRecordId"] for x in rows]
    if len(ids)!=len(set(ids)): raise SystemExit("Duplicate TBProfiler sourceRecordId values found")
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",newline="",encoding="utf-8") as h: w=csv.DictWriter(h,fieldnames=COLUMNS); w.writeheader(); w.writerows(rows)
    report={"datasetAccession":a.dataset_accession,"pipeline":"TBProfiler","pipelineVersion":a.tool_version,"databaseVersion":a.db_version,"samples":[{"sourceRecordId":r["sourceRecordId"],"qualityStatus":r["qualityStatus"],"summary":json.loads(r["summary"])} for r in rows],"jlightImportFile":str(a.output)}
    a.output.with_name("tbprofiler_validation_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
