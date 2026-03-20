"""Oula Trading - Technical Indicators + Legendary Strategies"""
import math
from typing import List
def sma(c: List[float], p: int) -> List[float]:
    r = []
    for i in range(len(c)):
        if i < p-1: r.append(None)
        else: r.append(sum(c[i-p+1:i+1])/p)
    return r
def ema(c: List[float], p: int) -> List[float]:
    r=[]; m=2/(p+1)
    for i in range(len(c)):
        if i < p-1: r.append(None)
        elif i == p-1: r.append(sum(c[:p])/p)
        else: r.append((c[i]-r[-1])*m+r[-1])
    return r
def rsi(c: List[float], p: int=14) -> List[float]:
    if len(c)<p+1: return [None]*len(c)
    g=[]; l=[]
    for i in range(1,len(c)):
        ch=c[i]-c[i-1]; g.append(max(0,ch)); l.append(max(0,-ch))
    ag=sum(g[:p])/p; al=sum(l[:p])/p; res=[None]*p
    for i in range(p): res.append(100 if al==0 else 100-100/(1+ag/al))
    for i in range(p,len(g)):
        ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p
        res.append(100 if al==0 else 100-100/(1+ag/al))
    return res
def macd(c, fast=12, slow=26, sig=9):
    ef=ema(c,fast); es=ema(c,slow)
    ml=[(ef[i]-es[i]) if ef[i] and es[i] else None for i in range(len(c))]
    vm=[v for v in ml if v is not None]; sl=ema(vm,sig)
    res_m=ml[:]; res_s=[None]*len(ml); res_h=[None]*len(ml); off=len(ml)-len(sl)
    for i,sv in enumerate(sl):
        m_val = res_m[off+i]
        res_s[off+i]=sv
        if m_val is not None and sv is not None:
            res_h[off+i]=m_val-sv
    return {"macd":res_m,"signal":res_s,"histogram":res_h}
def bollinger(c, p=20, ns=2.0):
    m=sma(c,p); u=[]; lo=[]
    for i in range(len(c)):
        if m[i] is None: u.append(None); lo.append(None)
        else:
            w=c[i-p+1:i+1]; sd=math.sqrt(sum((x-m[i])**2 for x in w)/p)
            u.append(m[i]+ns*sd); lo.append(m[i]-ns*sd)
    return {"upper":u,"middle":m,"lower":lo}
def atr(h, l, c, p=14):
    tr=[h[0]-l[0]]+[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return ema(tr,p)
def adx(h, l, c, p=14):
    if len(c)<p*2: return [None]*len(c)
    pdm=[]; mdm=[]
    for i in range(1,len(c)):
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        pdm.append(up if up>dn and up>0 else 0); mdm.append(dn if dn>up and dn>0 else 0)
    tr=[h[0]-l[0]]+[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    def ws(d,p):
        r=[None]*(p-1); r.append(sum(d[:p]))
        for i in range(p,len(d)): r.append(r[-1]-r[-1]/p+d[i])
        return r
    st=ws(tr,p); sp=ws(pdm,p); sm=ws(mdm,p); dx=[]
    for tv,pv,mv in zip(st,sp,sm):
        if tv==0 or pv is None or mv is None: dx.append(None)
        else:
            pdi=100*pv/tv; mdi=100*mv/tv; d=pdi+mdi
            dx.append(100*abs(pdi-mdi)/d if d!=0 else 0)
    vd=[v for v in dx if v is not None]
    if len(vd)<p: return dx
    av=[None]*(p-1); av.append(sum(vd[:p])/p)
    for i in range(p,len(vd)): av.append((av[-1]*(p-1)+vd[i])/p)
    res=[None]*len(dx); off=len(dx)-len(av)
    for i,v in enumerate(av):
        if v is not None: res[off+i]=v
    return res
def williams_pct_r(h, l, c, p=14):
    r=[]
    for i in range(len(c)):
        if i<p-1: r.append(None)
        else:
            hh=max(h[i-p+1:i+1]); ll=min(l[i-p+1:i+1])
            r.append((hh-c[i])/(hh-ll)*-100 if hh!=ll else -50)
    return r
def volume_ratio(v, p=20):
    av=sma(v,p)
    return [v[i]/av[i] if av[i] and av[i]>0 else None for i in range(len(v))]
def darvas_box(h, l, c, lookback=20):
    if len(c)<lookback: return {"error":f"need {lookback} bars"}
    top=max(h[-lookback:][:-1]); bot=min(l[-lookback:][:-1]); cur=c[-1]; tol=(top-bot)*0.02
    if cur>top+tol: pos="breaking_up"; sig="buy"
    elif cur<bot-tol: pos="breaking_down"; sig="sell"
    else:
        mid=(top+bot)/2; pos="inside_upper" if cur>mid else "inside_lower"; sig="hold"
    return {"box_top":round(top,2),"box_bottom":round(bot,2),"box_height":round(top-bot,2),"box_height_pct":round((top-bot)/bot*100,2) if bot>0 else 0,"current_price":cur,"position":pos,"signal":sig,"description":f"box [{bot:.2f}, {top:.2f}], price {cur:.2f}, {pos}"}
def livermore_breakout(h, l, c, v, lookback=20, vt=1.5):
    if len(c)<lookback+1: return {"error":"need more data"}
    res=max(h[-lookback-1:-1]); cur=c[-1]
    avg_v=sum(v[-lookback:-1])/lookback if v else 0; cur_v=v[-1] if v else 0; vr=cur_v/avg_v if avg_v>0 else 0
    if cur>res:
        if vr>=vt: sig="breakout"; conf=min(95,60+(vr-vt)*20)
        else: sig="false_breakout"; conf=30
    elif cur>res*0.97: sig="approaching"; conf=40
    else: sig="no_signal"; conf=10
    return {"breakout_level":round(res,2),"current_price":cur,"distance_to_breakout":round((res-cur)/res*100,2),"volume_ratio":round(vr,2),"signal":sig,"confidence":round(conf,1),"description":f"resistance {res:.2f}, price {cur:.2f}, vol_ratio {vr:.1f}x, {sig}"}
def trend_analysis(c, h, l):
    if len(c)<200: return {"error":"need 200 bars"}
    m20=sma(c,20); m50=sma(c,50); m200=sma(c,200)
    la20=m20[-1]; la50=m50[-1]; la200=m200[-1]; cur=c[-1]
    ax=adx(h,l,c,14); la_ax=ax[-1] if ax[-1] else 0
    if cur>la20>la50>la200: tr="strong_up"; desc="bullish alignment"
    elif cur>la50>la200: tr="up"; desc="uptrend"
    elif cur<la20<la50<la200: tr="strong_down"; desc="bearish alignment"
    elif cur<la50<la200: tr="down"; desc="downtrend"
    else: tr="sideways"; desc="no clear trend"
    st=min(100,la_ax*2)
    if tr in("strong_up","strong_down"): st=min(100,st+20)
    sug="go long" if tr in("strong_up","up") and st>40 else "go short or wait" if tr in("strong_down","down") and st>40 else "avoid trading" if tr=="sideways" else "caution"
    return {"current_price":cur,"ma20":round(la20,2),"ma50":round(la50,2),"ma200":round(la200,2),"adx":round(la_ax,1),"trend":tr,"strength":round(st,1),"description":desc,"suggestion":sug,"ma_alignment":{"ma20_vs_ma50":"above" if la20>la50 else "below","ma50_vs_ma200":"above" if la50>la200 else "below","price_vs_ma20":"above" if cur>la20 else "below"}}
def composite_signal(c, h, l, v):
    comp={}
    db=darvas_box(h,l,c); comp["darvas_box"]={"signal":db.get("signal","error"),"position":db.get("position","")}
    lb=livermore_breakout(h,l,c,v); comp["livermore_breakout"]={"signal":lb.get("signal","error"),"confidence":lb.get("confidence",0)}
    wr=williams_pct_r(h,l,c,14); lw=wr[-1] if wr and wr[-1] is not None else -50
    if lw<-80: ws="oversold"; wsc=2
    elif lw>-20: ws="overbought"; wsc=-2
    else: ws="neutral"; wsc=0
    comp["williams_pct_r"]={"value":round(lw,1),"signal":ws}
    rv=rsi(c,14); lr=rv[-1] if rv and rv[-1] is not None else 50
    if lr<30: rs="oversold"; rsc=2
    elif lr>70: rs="overbought"; rsc=-2
    else: rs="neutral"; rsc=0
    comp["rsi"]={"value":round(lr,1),"signal":rs}
    if len(c)>=200:
        ta=trend_analysis(c,h,l); comp["trend"]={"direction":ta.get("trend","sideways"),"strength":ta.get("strength",0)}
    else: comp["trend"]={"direction":"insufficient_data","strength":0}
    score=0; reasons=[]
    if comp["darvas_box"]["signal"]=="buy": score+=2; reasons.append("darvas breakout")
    elif comp["darvas_box"]["signal"]=="sell": score-=2; reasons.append("darvas breakdown")
    if comp["livermore_breakout"]["signal"]=="breakout": score+=3; reasons.append("livermore true breakout")
    elif comp["livermore_breakout"]["signal"]=="false_breakout": score-=1
    score+=wsc; score+=rsc
    if ws!="neutral": reasons.append(f"WR: {ws}")
    if rs!="neutral": reasons.append(f"RSI: {rs}")
    td=comp["trend"]["direction"]
    if td=="strong_up": score+=2; reasons.append("strong uptrend")
    elif td=="up": score+=1; reasons.append("uptrend")
    elif td=="strong_down": score-=2; reasons.append("strong downtrend")
    elif td=="down": score-=1; reasons.append("downtrend")
    if score>=5: ov="strong_buy"
    elif score>=3: ov="buy"
    elif score>=1: ov="weak_buy"
    elif score<=-5: ov="strong_sell"
    elif score<=-3: ov="sell"
    elif score<=-1: ov="weak_sell"
    else: ov="hold"
    conf=min(100,abs(score)*15)
    return {"overall_signal":ov,"score":score,"confidence":round(conf,1),"components":comp,"reasons":reasons,"current_price":c[-1],"summary":f"signal: {ov} (score: {score}, confidence: {conf}%)"}
