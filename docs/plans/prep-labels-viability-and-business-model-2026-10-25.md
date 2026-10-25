# Prep: viability, printer connection, voice, and business model

2026-10-25 · Builds on Noah's handoff (`~/Downloads/Prep-Printer-Research-Claude-Handoff.md`, not in this repo). This is a research draft, not a decision. Nothing has been built or tested on hardware.

## 1. What the product is

Someone in a kitchen says "four banana breads, six eggs". Prep turns that into clean names and quantities, stamps the prep time, and prints the right number of labels. Next it would become a hosted service, so the app, the voice assistants, and any kitchen's printer all go through one backend.

## 2. How kitchens print today

Kitchens have two kinds of printer, and they do different jobs.

| Kind | Typical hardware | Connection | Prep relevance |
|---|---|---|---|
| Order-ticket ("kitchen") printers | Epson TM-U220 impact printers (heat- and grease-resistant), Epson TM-T88 / Star thermal printers | Ethernet with a static IP, raw ESC/POS on TCP 9100. Epson/Star web printers use HTTP (Epson ePOS on 8008/8043) | Wrong device. They print receipt paper, not adhesive labels |
| Food-prep label printers | DayMark Matt85 (Android tablet + Bluetooth printer), Jolt Print Station, Epson TM-L100 (liner-free, IP22-equivalent, about £390–€420), Star mC-Label3 (about $685), Brother QL desktop printers | Bluetooth, Wi-Fi, Ethernet, cloud polling | **This is the market** |

The order-ticket printers belong to the POS. The label printer is a separate station on the prep line, usually driven by a tablet.

## 3. Connection: why not UDP

Using UDP is a reasonable instinct, but it's the wrong transport for print jobs:

- **Printers don't take print jobs over UDP.** UDP shows up only in **discovery**. Epson's ENPC on UDP 3289 broadcasts to find printers on the network, and SNMP on UDP 161 reports status. The jobs themselves travel over TCP (port 9100) or HTTP.
- **UDP fights the handoff's own acceptance tests.** UDP can drop or duplicate packets without telling you. Noah's spec requires that "a duplicate submission does not print twice" and that the app never claims success after an uncertain failure. That needs a reliable transport and a job ID.
- **The better model for a hosted service is that the printer calls us.** With **Star CloudPRNT** and **Epson Server Direct Print**, the printer polls the cloud over HTTPS and pulls waiting jobs. That means no open ports, no static IP, no firewall changes and no local computer. The cost is a few seconds of polling delay.

**Recommended layering:**

```
voice / app / Alexa ──► Prep cloud API ──(job queue, idempotent job IDs)──►
    ├─ Cloud-polling printers (Star CloudPRNT, Epson SDP): printer pulls over HTTPS
    └─ Bridge printers (Brother QL over Bluetooth/Wi-Fi): the Prep phone/tablet app pulls the job and prints through the Brother SDK
UDP only for discovering printers on the local network during setup.
```

There's a catch with Noah's first printer, the Brother QL-810Wc. It can't poll the cloud, so it always needs a bridge, and the natural bridge is a phone or tablet app. That supports the idea that **this should be an application**. The app holds the printer connection and the cloud holds everything else.

## 4. Voice: Siri, Alexa

- **Siri is the best fit.** If Prep is an iOS app, App Intents and Shortcuts let "Hey Siri, Prep four banana breads" reach the app directly, and the app prints through the Brother SDK. No extra server is needed for the first version.
- **Alexa needs the cloud.** The path is skill → Prep cloud → printer. It works with cloud-polling printers, or with a bridge app that's online. It's a good demo, and probably a second-phase feature.
- **Kitchen noise is the real risk (my inference, not tested).** Hoods, dish machines and shouting all hurt speech recognition. Plan on push-to-talk on the tablet, a "read it back" confirmation before printing, and a test in a working kitchen during service before promising anything.
- **Searches found no voice-first food-label product.** The closest are BradyVoice (voice-driven industrial labels, not kitchens) and FoodLabel (speech input, no printer). That gap is the opening. Voice is a feature competitors could copy, though, so the speed has to be real and measured.

## 5. Competition and price anchors

| Product | Model | Price seen |
|---|---|---|
| DayMark MenuPilot / Matt85 | Tablet + printer bundle, cloud menu management | Not public. A trade article describes a one-time cost |
| Jolt | Print station + cloud labeling app, bundled with checklists and compliance | Not public |
| Epson Food Freshness Label app | Browser app that prints to the printer's IP address | Free with Epson hardware. **This is an OEM threat** |
| PrepWizard | App + printer | About $120/yr app + $250 printer (vendor claim) |
| Andy | Labeling plan | €19.55 per location per month (annual) |
| KitchenNmbrs | Operations suite | €25–55 per location per month |

**Takeaway:** kitchens already pay about **$10–25 per location per month** for labeling alone, plus hardware. Prep fits that range. It doesn't create a new budget line.

## 6. Business model (draft)

**Revenue lines:**
1. **Subscription per location:**
   - Home/free tier (one printer, Siri, local only)
   - Pro at about $15–20 per location per month (cloud, Alexa, multiple devices, labeling history without transcripts)
   - Multi-location at about $12–15 per location per month, with central menu/item lists and manager controls
2. **Hardware bundle:** a printer plus starter rolls sold at a small margin, so setup is one box.
3. **Label consumables:** recurring roll shipments. This is the razor-and-blade part and likely the stickiest revenue. DayMark's core business is consumables.

**Unit economics to verify (not yet measured):** cloud cost per location should be cents per month, because jobs are tiny and polling is cheap. The main costs are support and printer setup. That supports using cloud-polling printers commercially, since there's no local IT.

**Distribution, from most to least promising:**
1. **Brother's ISV partner program.** It's free and includes SDKs, discounted test printers, engineering support, and possible co-marketing. It's the realistic way to get "offered when they sell the printer". Apply early, because the program exists for exactly this.
2. **POS dealers and distributors** such as BlueStar, which already resells Star CloudPRNT and Brother. Dealers install kitchen hardware and want add-on software.
3. **POS app marketplaces** (Toast, Square, Lightspeed). The menu items already live in the POS, which removes setup work.
4. **Approaching Epson and Star directly is the hardest route.** Epson ships its own free label app. Lead with something they lack (voice and speed) and with proof from real kitchens before pitching them.

## 7. Viability: my read

- **High confidence:** the market is real and already paying. The kitchen hardware and cloud-printing infrastructure exist. Nobody visible owns voice-first labeling.
- **Medium confidence:** voice is a strong enough reason to switch from tap-based tools. It depends on accuracy in noise and on measured seconds saved per batch.
- **Low confidence / unknown:** whether OEMs would bundle it, and how willing kitchens are to pay for a voice feature on its own versus a broader compliance suite like Jolt or Andy.

**Cheapest way to reduce the uncertainty:** follow Noah's handoff sequence (mock adapter → one real QL-810Wc label). Then time voice vs. tapping on 4- and 12-label batches in an actual kitchen, and interview 5–10 kitchen managers about what they use and pay now. That fits Noah's ESBM 4830 venture work.

## 8. Open questions for Gil / Noah

1. Is this Noah's venture with Gil as builder, as with SlopeCycle, or a joint company? It affects repo ownership and pitch materials.
2. Is the first target Noah's home kitchen (Brother QL + Siri) or a commercial pilot (cloud-polling printer + Alexa)? The answer picks the architecture.
3. Where is the current code? The last known build is a ChatGPT-hosted prototype, and there's no repo here yet.
4. Is there budget for one test printer (about $200 for the QL-810Wc + roll)? Or apply to Brother ISV first for a discounted unit?

## Sources

- Noah's handoff: `~/Downloads/Prep-Printer-Research-Claude-Handoff.md` (Brother/DYMO/Zebra/Star sources inside)
- Kitchen printers / TCP 9100: https://o-series-support.lightspeedhq.com/hc/en-us/articles/51460544683035-Setting-up-the-Epson-TM-U220B-TM-U220IIB-printer, https://docs.wcpos.com/templates/printer-setup
- Cloud polling: https://docs.wcpos.com/receipts/cloud-printing, https://star-emea.com/products/cloudprnt/, https://media.starmicronics.com/hubfs/Spec%20Sheets/CloudPRNT_Spec%20Sheet%20-Online%20Food%20Order_02-23-2021.pdf
- Epson ENPC UDP 3289: https://epson.com/faq/SPT_C11CJ03201~faq-0000525-shared
- Epson TM-L100: https://shop.triniteq.com/products/epson-label-printer-tm-l100, https://www.comercialtpv.com/en/epson-tm-l100-121-label-printer-direct-thermal-203.html
- Epson Food Freshness app: https://files.support.epson.com/docid/cpd5/cpd55393/source/sd/source/freshness_label_app/tasks/freshness_app_printing_labels.html
- DayMark MenuPilot: https://thecaterer.com/products/food-labeller-from-daymark, https://cmmonline.com/articles/the-right-answer-to-restaurants-food-labeling-needs
- Jolt: https://restaurantleadership.com/jolt-print-station
- Pricing: https://andyapp.io/?p=2095, https://www.g2.com/products/kitchennmbrs/pricing, https://prep-wizard.com/trial-competitor/
- Voice: https://www.voltimum.co.uk/news/brady/hands-free-labelling-discover-the-power-of-bradyvoice, https://apps.apple.com/kr/app/id6751731359
- Brother ISV: https://brother-usa.com/business/mobile/partner-program, https://www.brother.com.au/en/support/isv-partnership, https://bluestarinc.com/en-us/manufacturers/brother-mobile/brother-mobile-partner-program
