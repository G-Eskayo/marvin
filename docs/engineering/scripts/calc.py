import CoolProp.CoolProp as CP
K=273.15
fluids=["R1234ze(E)","R1234yf","R134a","R1233zd(E)","R245fa","R1336mzz(Z)","n-Pentane","Isobutane","Water","Ethanol","Methanol","Ammonia","Acetone","n-Butane"]
print("Psat bar(abs) at T(C): 0,20,40,60,80 ; Tboil@1atm ; hfg@40C kJ/kg")
for f in fluids:
    try:
        ps=[CP.PropsSI('P','T',t+K,'Q',0,f)/1e5 for t in (0,20,40,60,80)]
        tb=CP.PropsSI('T','P',101325,'Q',0,f)-K
        hfg=(CP.PropsSI('H','T',40+K,'Q',1,f)-CP.PropsSI('H','T',40+K,'Q',0,f))/1e3
        print(f"{f:12s}", " ".join(f"{p:8.3f}" for p in ps), f"| Tb={tb:6.1f} | hfg={hfg:6.0f}")
    except Exception as e: print(f,"ERR",e)
# Merit number for thermosiphon M = rho_l^2 * sigma * hfg / mu_l ... use figure of merit for thermosyphon (rho_l^2 * hfg * k_l^3 / mu_l)^0.25 (condensation)
print("\nThermosiphon figure of merit at 50C: (k^3 rho^2 hfg/mu)^0.25 ; vapour density")
for f in fluids:
    try:
        T=50+K
        k=CP.PropsSI('L','T',T,'Q',0,f); rho=CP.PropsSI('D','T',T,'Q',0,f); mu=CP.PropsSI('V','T',T,'Q',0,f)
        h=CP.PropsSI('H','T',T,'Q',1,f)-CP.PropsSI('H','T',T,'Q',0,f); rv=CP.PropsSI('D','T',T,'Q',1,f)
        print(f"{f:12s} M={ (k**3*rho**2*h/mu)**0.25:8.0f}  rho_v={rv:7.3f} kg/m3  vol.heat={rv*h/1e3:8.1f} kJ/m3")
    except Exception as e: print(f,"ERR",e)
# Dew points
print("\nDew point (C) for T=25C at RH 30,50,70")
for rh in (0.3,0.5,0.7):
    import math
    a,b=17.62,243.12; g=math.log(rh)+a*25/(b+25); print(rh, round(b*g/(a-g),1))
# Carnot heat-driven COP
print("\nCarnot heat-driven COP = (1-Ta/Tg)*Tc/(Ta-Tc)")
for Ta in (25,30,35):
  for Tg in (50,60,70,80,90,100,150):
    row=[]
    for Tc in (10,15,20):
        cop=(1-(Ta+K)/(Tg+K))*(Tc+K)/(Ta-Tc)
        row.append(f"{cop:5.2f}")
    print(f"Ta={Ta} Tg={Tg}: Tc=10,15,20 ->", " ".join(row))
