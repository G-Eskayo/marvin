import math
K=273.15
print("## Table A: cold produced from FIXED drive heat Qg=100 W at Tg=80C, heat rejection at Tr=35C (room 25 + 10K approach)")
print("Tc | Carnot COP | Qcold Carnot | 50% Carnot | 30% Carnot | heat rejected@30%")
for Tc in (30,20,10,0,-10):
    if Tc>=35: continue
    cop=(1-(35+K)/(80+K))*(Tc+K)/(35-Tc)
    print(f"{Tc:4d} | {cop:5.2f} | {100*cop:6.0f} W | {50*cop:5.0f} W | {30*cop:5.0f} W | {100+30*cop:5.0f} W")
print("\n## Table A2: same at Tg=60C (CPU-driven ceiling for old chips)")
for Tc in (30,20,10,0,-10):
    cop=(1-(35+K)/(60+K))*(Tc+K)/(35-Tc)
    print(f"{Tc:4d} | {cop:5.2f} | {100*cop:6.0f} W | {50*cop:5.0f} W | {30*cop:5.0f} W")
print("\n## Table B: drive heat needed to remove 100 W at Tc, Tg=80, Tr=35, at 30% / 50% of Carnot, and real silica-gel-like COP cap 0.5")
for Tc in (30,20,10,0,-10):
    cop=(1-(35+K)/(80+K))*(Tc+K)/(35-Tc)
    for f in (0.3,0.5):
        c=min(cop*f,0.6)
        print(f"Tc={Tc:4d} f={f}: COP={c:4.2f} drive={100/c:6.0f} W reject={100+100/c:6.0f} W")
print("\n## Table C: vapour-compression electrical COP (Carnot Tc/(Tcond-Tc), Tcond=45C) and real at 35% Carnot; wall W for 100 W")
for Tc in (20,10,0,-10,-25):
    c=(Tc+K)/(45-Tc); r=0.35*c
    print(f"Tc={Tc:4d}: Carnot {c:5.2f} real~{r:4.2f} wall={100/r:5.0f} W")
print("\n## Leakage: fraction saved going from T1 to T2 with doubling interval D")
for D,node in ((45,'65nm'),(22,'32nm')):
  for leak0 in (15,25,35):
    for T1,T2 in ((70,40),(70,20),(70,5)):
        new=leak0*2**(-(T1-T2)/D)
        print(f"{node} D={D}K leak@70C={leak0}W {T1}->{T2}C saves {leak0-new:5.1f} W")
print("\n## Arrhenius life factor Ea=0.7eV (EM), and caps 2x/10K")
k=8.617e-5
for T1,T2 in ((70,60),(70,50),(70,40),(70,30),(70,20)):
    af=math.exp(0.7/k*(1/(T2+K)-1/(T1+K)))
    print(f"{T1}->{T2}: EM x{af:5.1f}; caps(if same delta) x{2**((T1-T2)/10):5.1f}")
print("\n## Sorption bed sizing for 100 W for 8 h (intermittent) ")
E=100*8*3600
for name,hfg,swing in (("water/silica gel",2.47e6,(0.08,0.15)),("methanol/AC",1.17e6,(0.10,0.18)),("NH3/water (Icyball, per kg NH3)",1.26e6,None)):
    m=E/hfg
    if swing: print(f"{name}: refrigerant {m:4.2f} kg; sorbent {m/swing[1]:4.1f}-{m/swing[0]:4.1f} kg")
    else: print(f"{name}: ammonia {m:4.2f} kg")
print("\n## Continuous two-bed: sorbent mass for 100 W at SCP 50-200 W/kg:", [round(100/s,2) for s in (50,100,200)],"kg")
print("\n## Candle: 77 W heat; 3 candles = 231 W; at COP 0.1-0.2 (intermittent NH3/AC) cold =", [round(231*c) for c in (0.1,0.2)],"W")
print("\n## hot-drives-cold: VRM loss for 100 W CPU at 85-90% eff:", [round(100/e-100,1) for e in (0.85,0.9)],"W; cold at COP 0.3-0.5:",[round(x,1) for x in (11*0.3,17.6*0.5)])
