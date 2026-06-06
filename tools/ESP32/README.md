Since my S1S2 lines are only 5V I setup my hardware almost like XYE using a ESP32 and a RS485 to TTL board.
You must wire ESP32 ground to TTL ground and also ESP32 ground to RS485 ground.
This yaml pick up the signal from my 5V S1S2 lines using the RS485 to TTL board and throws it to my network.
The result mimics my orignal Waveshare I had connected and documented in the main README.md.

Dont assume your S1S2 lines are 5V, GET A CERTIFIED ELECTRICAN TO TEST YOUR LINES.
