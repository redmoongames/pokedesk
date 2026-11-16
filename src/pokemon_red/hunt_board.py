"""Four persistent background assignments, separate from the local main slot."""
from dataclasses import asdict
from .acquisition import AcquisitionManager,AcquisitionConfig,read_json,write_json
from .acquisition import job_active as active

class HuntBoard:
    def __init__(self,project):
        self.manager=AcquisitionManager(project);self.path=self.manager.folder/'slots.json';self.data=read_json(self.path)
        if not isinstance(self.data,dict) or len(self.data.get('slots',[]))!=4:
            self.data=dict(schema_version=1,slots=[dict(config=None,job_id=None) for _ in range(4)])
            # Preserve existing jobs, especially the already found shiny.
            jobs=self.manager.jobs()
            for slot,row in zip(self.data['slots'],jobs[:4]):slot.update(config=row['config'],job_id=row['id'])
            self.save()
    def save(self):write_json(self.path,self.data)
    def slot(self,index):
        if type(index) is not int or not 0<=index<4:raise ValueError('Номер слота: 1–4')
        return self.data['slots'][index]
    def assign(self,index,config):
        slot=self.slot(index);row=self.row(index)
        if row and active(row):raise ValueError('Сначала останови этот слот')
        slot.update(config=asdict(AcquisitionConfig.parse(config)),job_id=None);self.save()
    def start(self,index):
        slot=self.slot(index);row=self.row(index)
        if not slot['config']:raise ValueError('Сначала назначь Pokémon')
        if row:
            if row.get('status') in ('ready','transferred'):raise ValueError('Этот слот уже завершён')
            if row.get('status')=='cancelled':raise ValueError('Назначь Pokémon заново для нового поиска')
            self.manager.resume(row['id'])
        else:slot['job_id']=self.manager.start(slot['config']);self.save()
    def pause(self,index):
        slot=self.slot(index)
        if slot['job_id']:self.manager.pause(slot['job_id'])
    def cancel(self,index):
        slot=self.slot(index)
        if slot['job_id']:self.manager.cancel(slot['job_id'])
        else:slot.update(config=None,job_id=None);self.save()
    def reconcile(self,rows):
        """Archive completed transfers/cancellations without erasing donor saves."""
        changed=False
        for index in range(4):
            slot=self.slot(index);row=self.row(index,rows)
            if row and row.get('status') in ('transferred','cancelled') and not active(row):
                self.data.setdefault('history',[]).append(dict(slot=index,job_id=row['id'],config=slot['config'],status=row['status']))
                slot.update(config=None,job_id=None);changed=True
        if changed:self.save()
    def row(self,index,rows=None):
        slot=self.slot(index)
        return next((r for r in (rows if rows is not None else self.manager.jobs()) if r['id']==slot['job_id']),None)
