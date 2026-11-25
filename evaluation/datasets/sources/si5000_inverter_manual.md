# SI-5000 Solar Inverter Maintenance Manual

This manual describes routine maintenance of the SI-5000 string inverter used at Northwind Energy solar sites. Maintenance must only be carried out by qualified electrical technicians.

## Safety Before Maintenance

Before opening the inverter enclosure, switch off the AC breaker and then isolate the DC disconnect switch. Wait at least five minutes for the internal capacitors to discharge before touching any internal component. Verify the absence of voltage with a calibrated multimeter on both the DC and AC terminals.

Technicians must wear insulated gloves and safety glasses during all maintenance work on the inverter.

=== PAGE ===

## Quarterly Inspection

Every quarter, perform a visual inspection of the inverter enclosure, cable glands and mounting brackets. Check that the cooling fan rotates freely and is not obstructed by debris or insect nests. Record the inverter operating temperature and the daily energy yield from the display.

## Air Filter Cleaning

The air filters must be cleaned every six months using low-pressure compressed air. Replace the air filters every two years, or immediately if they are torn or clogged with oil.

## Cooling Fan Replacement

Replace the cooling fan if it produces grinding noise, if its speed falls below 2000 rpm, or after 50000 operating hours, whichever comes first.

=== PAGE ===

## Annual Electrical Inspection

Once per year, tighten all DC terminals to a torque of 2.5 Nm and all AC terminals to a torque of 4.0 Nm using a calibrated torque wrench. Measure the insulation resistance of the PV array; a reading below 1 megaohm indicates an insulation fault that must be investigated before the inverter is restarted.

## Firmware Updates

Firmware updates are installed from a USB drive through the service port. Check the firmware version on the display under Settings, then System Information. Never disconnect power during a firmware update; an interrupted update requires a factory reset by the manufacturer.

=== PAGE ===

## Error Codes

The display shows error codes when a fault is detected:

- E-21 Ground fault: an insulation fault between the PV array and earth. Inspect cables for damage.
- E-34 Grid overvoltage: the grid voltage exceeded the configured limit. The inverter reconnects automatically after 5 minutes.
- E-47 Overtemperature: the heat sink exceeded 85 degrees Celsius. Check the cooling fan and air filters.
- E-52 Communication loss: the monitoring gateway has not responded for 15 minutes.

## Warranty

The SI-5000 is covered by a 10 year manufacturer warranty. The warranty is void if maintenance records are not kept or if the enclosure is opened by unqualified personnel.
