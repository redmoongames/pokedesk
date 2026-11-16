/* Cooperative two-GBA scheduling around mGBA's original SIO lockstep driver.
 * Both emulators remain on the caller's thread. No Pokémon/save data edits. */
#include <mgba/internal/gba/gba.h>
#include <mgba/internal/gba/sio/lockstep.h>
#include <stddef.h>

typedef struct {
    struct mLockstepUser d;
    int asleep;
    int id;
} PokemonLinkUser;
typedef struct {
    struct GBASIOLockstepCoordinator coordinator;
    struct GBASIOLockstepDriver drivers[2];
    PokemonLinkUser users[2];
    Pokemon *games[2];
    uint64_t cycles[2];
    uint32_t lastCycle[2];
} PokemonLink;
static void link_sleep(struct mLockstepUser *u) { ((PokemonLinkUser*)u)->asleep=1; }
static void link_wake(struct mLockstepUser *u) { ((PokemonLinkUser*)u)->asleep=0; }
static int link_requested(struct mLockstepUser *u) { return ((PokemonLinkUser*)u)->id; }
static void link_changed(struct mLockstepUser *u,int id) { (void)u;(void)id; }
PokemonLink *pokemon_link_open(Pokemon *a,Pokemon *b) {
    if (!a || !b || a==b) return NULL;
    PokemonLink *link=calloc(1,sizeof(*link));if (!link) return NULL;
    link->games[0]=a;link->games[1]=b;
    GBASIOLockstepCoordinatorInit(&link->coordinator);
    for (int i=0;i<2;i++) {
        link->lastCycle[i]=mTimingCurrentTime(&((struct GBA*)link->games[i]->core->board)->timing);
        link->users[i].d=(struct mLockstepUser){link_sleep,link_wake,link_requested,link_changed};link->users[i].id=i;
        GBASIOLockstepDriverCreate(&link->drivers[i],&link->users[i].d);
        GBASIOLockstepCoordinatorAttach(&link->coordinator,&link->drivers[i]);
        GBASIOSetDriver(&((struct GBA*)link->games[i]->core->board)->sio,&link->drivers[i].d);
    }
    return link;
}
int pokemon_link_step(PokemonLink *link,unsigned a,unsigned b,unsigned frames) {
    if (!link || frames>3600) return 0;
    unsigned target[2];
    for (int i=0;i<2;i++){link->games[i]->core->setKeys(link->games[i]->core,i?b:a);target[i]=link->games[i]->core->frameCounter(link->games[i]->core)+frames;}
    for (unsigned loop=0;loop<20000000;loop++) {
        unsigned now[2];for(int i=0;i<2;i++)now[i]=link->games[i]->core->frameCounter(link->games[i]->core);
        if ((int)(now[0]-target[0])>=0 && (int)(now[1]-target[1])>=0) return 1;
        int chosen=-1;
        for(int i=0;i<2;i++)if(!link->users[i].asleep && (chosen<0 || link->cycles[i]<link->cycles[chosen]))chosen=i;
        if(chosen<0){fprintf(stderr,"LINK DEADLOCK sleep=%d,%d cycles=%llu,%llu frames=%u,%u target=%u,%u\n",link->users[0].asleep,link->users[1].asleep,(unsigned long long)link->cycles[0],(unsigned long long)link->cycles[1],now[0],now[1],target[0],target[1]);return 0;}
        Pokemon *p=link->games[chosen];p->core->runLoop(p->core);
        uint32_t cycle=mTimingCurrentTime(&((struct GBA*)p->core->board)->timing);
        link->cycles[chosen]+=(uint32_t)(cycle-link->lastCycle[chosen]);link->lastCycle[chosen]=cycle;
        mAudioBufferClear(p->core->getAudioBuffer(p->core));
    }
    fprintf(stderr,"LINK LIMIT sleep=%d,%d cycles=%llu,%llu frames=%u,%u target=%u,%u waiting=%u active=%d attached=%d\n",link->users[0].asleep,link->users[1].asleep,(unsigned long long)link->cycles[0],(unsigned long long)link->cycles[1],link->games[0]->core->frameCounter(link->games[0]->core),link->games[1]->core->frameCounter(link->games[1]->core),target[0],target[1],link->coordinator.waiting,link->coordinator.transferActive,link->coordinator.nAttached);
    for(int i=0;i<2;i++){struct GBASIOLockstepPlayer *p=TableLookup(&link->coordinator.players,link->drivers[i].lockstepId);fprintf(stderr,"player %d asleep=%d mode=%d id=%d time=%u offset=%d queue=%p\n",i,p->asleep,p->mode,p->playerId,mTimingCurrentTime(&((struct GBA*)link->games[i]->core->board)->timing),p->cycleOffset,(void*)p->queue);}
    return 0;
}
void pokemon_link_close(PokemonLink *link) {
    if(!link)return;
    for(int i=0;i<2;i++)GBASIOSetDriver(&((struct GBA*)link->games[i]->core->board)->sio,NULL);
    GBASIOLockstepCoordinatorDeinit(&link->coordinator);free(link);
}
