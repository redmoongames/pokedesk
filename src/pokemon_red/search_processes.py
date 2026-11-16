"""Bounded cooperative teardown shared by isolated search process pools."""
import time

def stop_children(children):
    # One deadline for the whole pool: one hung child cannot delay all others.
    for action,seconds in ((None,2),('terminate',2),('kill',1)):
        for _,process,_ in children:
            if process.poll() is None and action:getattr(process,action)()
        deadline=time.monotonic()+seconds
        while any(p.poll() is None for _,p,_ in children) and time.monotonic()<deadline:time.sleep(.015)
        if all(p.poll() is not None for _,p,_ in children):break
    for _,process,log in children:
        process.wait(timeout=1);log.close()

