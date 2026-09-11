from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base
from app.models.core import Period, UploadedFile, Job
from app.models.accounting import OrganizationMapping, PersonnelMasterArtifact
from app.services.job_runner import run_job
from app.services.monthly_personnel import normalize, reconcile_people


def person(name, employee, cert):
    return {"姓名":name,"员工编号":employee,"证件号码":cert,"证件类型":"居民身份证","机构代码":"13208","人员状态":"正常","手机号码":"13800138000","任职受雇从业日期":"2026-01-01"}


@pytest.mark.parametrize("code,kind,role,income", [
    ("broker_tax","broker","broker_income",{"姓名":"张三","员工编号":"1001","经纪人本期收入":1000}),
    ("intern_tax","intern","intern_salary",{"*姓名":"张三","工号":"1001","*证件类型":"居民身份证","*证件号码":"110101199003072015","机构代码":"13208","实习开始时间":"2026-08-01","发放补贴数（元）":1000}),
    ("part_time_tax","part_time","payroll",{"姓名":"张三","本期收入":1000}),
])
def test_review_generate_and_departures(tmp_path,monkeypatch,code,kind,role,income):
    monkeypatch.setattr(settings,"storage_root",tmp_path)
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        p=Period(year=2026,month=8,name='2026-08');db.add(p)
        db.add(OrganizationMapping(org_code='13208',branch_name='营业部一'));db.commit()
        source=tmp_path/'master.xlsx'
        pd.DataFrame([person('张三','1001','110101199003072015'),person('李四','1002','110101199003072023')]).to_excel(source,index=False)
        db.add(PersonnelMasterArtifact(period_id=p.id,person_type=kind,scope_type='month',scope_code='',file_name=source.name,stored_path=str(source),row_count=2));db.commit()
        payroll=tmp_path/'income.xlsx';pd.DataFrame([income]).to_excel(payroll,index=False)
        f=UploadedFile(period_id=p.id,file_role=role,original_name=payroll.name,stored_path=str(payroll),size_bytes=payroll.stat().st_size)
        db.add(f);db.commit()
        def run(operation,ids):
            job=Job(period_id=p.id,workflow_code=code,input_file_ids=ids,operation=operation,status='pending');db.add(job);db.commit()
            return run_job(db,job,operation)
        initial=run('initial',[f.id])
        assert initial.status=='success', (initial.error_message, initial.result_summary)
        assert initial.result_summary['leaver_count']==1
        assert not any(a.artifact_type=='declaration' for a in initial.artifacts)
        final=run('generate',[])
        assert final.status=='success', (final.error_message,final.result_summary)
        assert any(a.artifact_type=='declaration' for a in final.artifacts)
        saved=db.query(PersonnelMasterArtifact).filter_by(period_id=p.id,person_type=kind).one()
        data=pd.read_excel(saved.stored_path).set_index('*姓名')
        assert data.loc['李四','人员状态']=='非正常'
        assert data.loc['张三','人员状态']=='正常'
        assert source.exists()


def test_absence_not_zero_and_ambiguous_match_never_finalizes_departures():
    master=normalize(pd.DataFrame([person('张三','1001','1'),person('李四','1002','2')]))
    payroll=normalize(pd.DataFrame([{'姓名':'张三','本期收入':0}]))
    updated,changes,_,issues=reconcile_people(master,payroll,2026,8)
    assert not issues
    assert [r['*姓名'] for r in changes if r['变更类型']=='离职']==['李四']
    master[1]['*姓名']='张三'
    updated,changes,_,issues=reconcile_people(master,payroll,2026,8)
    assert issues and not changes


def test_departure_missing_fields_and_excel_recheck():
    master=normalize(pd.DataFrame([person('张三','1001','1'),person('李四','1002','2')]))
    master[1]['手机号码']=''
    payroll=normalize(pd.DataFrame([{'姓名':'张三','本期收入':1000}]))
    _,changes,_,issues=reconcile_people(master,payroll,2026,8)
    assert issues[0]['missing_fields']==['手机号码']
    changes[0]['手机号码']='13900139000'
    changes[0]['任职受雇从业日期']=''
    updated,_,_,issues=reconcile_people(master,payroll,2026,8,changes)
    assert not issues
    assert updated[1]['任职受雇从业日期']=='2026-01-01'
