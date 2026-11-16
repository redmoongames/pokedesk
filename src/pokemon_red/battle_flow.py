"""Explicit single-battle UI phases, including the gap between two opponents."""
PARTY_CALLBACKS={'CB2_UpdatePartyMenu','CB2_InitPartyMenu','CB2_ReturnToPartyMenuFromSummaryScreen'}
SUMMARY_CALLBACKS={'CB2_SetUpPSS','CB2_RunPokemonSummaryScreen','CB2_ShowPokemonSummaryScreen'}
BAG_CALLBACKS={'CB2_BagMenuRun','CB2_BagMenu','CB2_OpenBagMenu','CB2_BagMenuFromBattle'}
SAFE_PHASES={'message','yes_no','party','party_context','party_blocked','party_message','item_target','summary','bag','move_order','target','wait'}

def phase(state):
    if not state.get('in_battle'):return 'finished'
    c=state.get('controls',{});b=state.get('battle') or {};cb=c.get('callback');tasks={t['name'] for t in c.get('tasks',[])}
    if state.get('decision') or c.get('summary_mode') in (2,3):return 'learn_move'
    if b.get('outcome') in (2,3,9):return 'lost'
    if cb in SUMMARY_CALLBACKS:return 'summary'
    if cb in BAG_CALLBACKS:return 'bag'
    if cb in PARTY_CALLBACKS:
        if c.get('party_action') in (3,14):return 'item_target'
        if c.get('party_action') in (2,4):return 'party_blocked'
        if 'Task_HandleSelectionMenuInput' in tasks:return 'party_context'
        if 'Task_HandleChooseMonInput' in tasks:return 'party'
        if tasks&{'Task_ReturnToChooseMonAfterText','Task_PrintAndWaitForText','Task_PrintAndWaitForText2'}:return 'party_message'
        return 'wait'
    if cb!='BattleMainCB2':return 'wait'
    if c.get('battle_script_opcode') in (0x5a,0x5b) and c.get('learn_move_state')==1:return 'learn_move'
    if c.get('battle_script_opcode')==0x67:return 'yes_no' if c.get('yes_no_state')==1 else 'wait'
    if b.get('outcome'):return 'message'
    controller=(c.get('controllers') or [''])[0]
    if controller=='HandleInputChooseAction':return 'action'
    if controller=='HandleInputChooseMove':return 'move'
    if controller=='HandleMoveSwitching':return 'move_order'
    if controller=='HandleInputChooseTarget':return 'target'
    return 'message'


def ready(state):
    p=phase(state);b=state.get('battle') or {}
    if p in SAFE_PHASES:return True
    return p in ('action','move') and state.get('telemetry_valid',True) and b.get('telemetry_valid',True) and len(b.get('allies',[]))==len(b.get('enemies',[]))==1
