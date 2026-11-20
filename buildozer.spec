[app]
title = STAR-CAR
package.name = starcar
package.domain = org.starking
source.dir = .
source.include_exts = py,txt
version = 1.1
requirements = python3,kivy==2.3.0,pyjnius,pyserial,requests,plyer,usb4a,usbserial4a,android
orientation = landscape
fullscreen = 0
android.permissions = INTERNET,RECORD_AUDIO
android.api = 33
android.minapi = 21
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
