# Free live news and natural events

Data Pool collects GDELT Project event data, USGS earthquakes and NASA EONET
natural-event metadata through their public endpoints. These collectors use no
subscription or API key. GDELT Project's data terms permit commercial use and
redistribution with attribution and a link to https://www.gdeltproject.org/.

The news collector checks every ten minutes and reads the latest hour of published
15-minute GDELT event files. It keeps up to ten matching events per region, including
the GDELT ID, actor names, event category, action location, event date and original
report link. The displayed description is generated from structured fields.
GDELT coding is automated and can be inaccurate. Collection time and event date
are recorded separately. Articles and publisher headlines are not downloaded.

USGS and NASA checks run every thirty minutes through the existing proximity
matching, source references and two-hour expiry rules. Event proximity does not
establish local impact. EONET event extents are approximate.

The authenticated hosted refresh route claims due checks in PostgreSQL before
running them. Existing workers also use the normal connector scheduler. Signals
enter the existing Data Pool and simulation snapshot flow.

Sources are registered with verified free-data terms. Existing source records must
be updated with the same approval metadata during rollout. The optional paid World
Monitor API connector has been removed. Existing historical source records can be
retained as deprecated records.

References are https://www.gdeltproject.org/about.html,
https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf,
https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits,
and https://eonet.gsfc.nasa.gov/what-is-eonet.
