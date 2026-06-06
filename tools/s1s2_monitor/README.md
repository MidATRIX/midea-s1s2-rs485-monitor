Can be use with actual S1S2 bus or S1S2 simulator

```
Usage: nc <tcp:ip> <port> | python3 s1s2_monitor.py <flag>
Optional Flags:  --fahrenheit | -f | -F    (default) --celsius | -c | -C

ESP32 and Waveshare example: nc 192.168.86.185 9999 | python3 s1s2_monitor_edit.py -f 
Simulator example: nc 127.0.0.1 5555 | python3 s1s2_monitor_edit.py -f
```

I orignaly used this to help decode without having a venv and pip installs.
Sensor data is not fully accurate.
Decoding logic in main loop around line 906
Defaults to a screensaver if no connection.
If you would like to help me decode run this with the S1S2 simulator.

Mostly created with AI.

---

## License

[MIT License](LICENSE)
