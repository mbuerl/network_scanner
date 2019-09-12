#!/usr/bin/python3
#basic source: https://stackoverflow.com/questions/207234/list-of-ip-addresses-hostnames-from-local-network-in-python

import os
import RPi.GPIO as GPIO
import socket    
import multiprocessing
import subprocess
import struct
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading


# debugging mode on or off
#debug=True
debug=False

# list of machines that need compressors
#watchlist = []
watchlist = ['192.168.229.223', '192.168.229.225', '192.168.229.226', '192.168.229.227', '192.168.229.181']
# ping intervall time in seconds
intervall_time_seconds = 120
# minutes to wait before compressors turn off when no watchlist member is running
compressor_off_delay_minutes = 4


threading_killflag = False
s_active_ip_list = list()
s_active_wachtlist_list = list()


class cPinger:
    def __init__(self):
        if debug:
            print('cListHandler starting')

    def ping_worker(self, job_q, results_q):
        """
        Do Ping
        :param job_q:
        :param results_q:
        :return:
        """
        DEVNULL = open(os.devnull, 'w')
        while True:
            ip = job_q.get()
            if ip is None:
                break
            else:
#                if debug:
#                    print('got ip to check ',ip)
                try:
                    subprocess.check_call(['ping', '-c 1 ', ip], stdout=DEVNULL)
                    results_q.put(ip)
                except:
                    pass


    def get_my_ip(self):
        """
        Find my IP address
        :return:
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.229.250", 80))
        ip = s.getsockname()[0]
        s.close()
#        if debug:
#            print('  my own ip: ', ip)
        
        return ip


    def map_network(self, pool_size=255):
        """
        Maps the network
        :param pool_size: amount of parallel ping processes
        :return: list of valid ip addresses
        """

        ip_list = list()

        # get my IP and compose a base like 192.168.1.xxx
        ip_parts = self.get_my_ip().split('.')
        base_ip = ip_parts[0] + '.' + ip_parts[1] + '.' + ip_parts[2] + '.'

        # prepare the jobs queue
        jobs = multiprocessing.Queue()
        results = multiprocessing.Queue()

        pool = [multiprocessing.Process(target=self.ping_worker, args=(jobs, results)) for i in range(pool_size)]

        # start pool pingers
        for p in pool:
            p.start()

        # cue the ping processes
        for i in range(1, 254):
            jobs.put(base_ip + '{0}'.format(i))

        for p in pool:
            jobs.put(None)

        for p in pool:
            p.join()

        # collect the results
        while not results.empty():
            ip = results.get()
            ip_list.append(ip)

        return ip_list


class cListHandler:
    def __init__(self):
        if debug:
            print('cListHandler starting')

        self.pinger = cPinger()
        self.rhandler = cRelayHandler()
        self.thread = threading.Thread(name='thread_periodical_checker', target=self.periodical_ckecker)
        self.thread.setDaemon(False)
        self.thread.start()

    def terminate(self):
        threading_killflag = True
        time.sleep(2.0)
        self.thread.join()
        self.rhandler.terminate()

    def periodical_ckecker(self):
        if debug:
            print('thread periodical_checker starting')

        self.delay_count = 0
        self.checkcount_to_poweroff = int((compressor_off_delay_minutes*60)/intervall_time_seconds)
        if debug:
            print(self.checkcount_to_poweroff, ' ping checks until compressor turnoff')

        while threading_killflag == False:
            try:
                self.active_ip = self.pinger.map_network()
                self.get_hostname(self.active_ip)
            except:
                if debug:
                    print("Error getting active IP List")

            #logic for poweroff delay
            self.active_intersection = list(set(watchlist) & set(self.active_ip))
            if debug:
                print(self.active_intersection," items found")

            if len (self.active_intersection) > 0:
                self.delay_count = 0
                self.rhandler.switch_on()
            else:
                self.delay_count += 1
                if self.delay_count <= self.checkcount_to_poweroff: 
                    pass
                else:
                    self.rhandler.switch_off()
            time.sleep(intervall_time_seconds)

    def get_hostname(self, active_ip):
        #sort active ip list
        s_active_ip = sorted (active_ip, key=lambda ip: struct.unpack("!L", socket.inet_aton(ip))[0])
        s_active_ip_list.clear()
        s_active_wachtlist_list.clear()
        for ip in s_active_ip:
            time.sleep(0.1)
            try:
                #returns triple (hostname, aliaslist, ipaddrlist)
                hostname = socket.gethostbyaddr(ip)[0]

            except:
                hostname = "#Unknown"

#            if debug:
#                print('   ip and hostname: ',ip,' ',hostname)

            if ip in watchlist:
                s_active_ip_list.append(str(ip + " " + hostname + " " + "in watchlist"))
                s_active_wachtlist_list.append(str(ip + " " + hostname))
            else:
                s_active_ip_list.append(str(ip + " " + hostname))
        
class cRelayHandler:
    def __init__(self):
        if debug:
            print('cRelayHandler starting')
        self.Relay_Ch1 = 26
        self.Relay_Ch2 = 20
        self.Relay_Ch3 = 21

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        GPIO.setup(self.Relay_Ch1,GPIO.OUT)
        GPIO.setup(self.Relay_Ch2,GPIO.OUT)
        GPIO.setup(self.Relay_Ch3,GPIO.OUT)

    def terminate(self):
        if debug:
            print(datetime.now().strftime("%d-%m-%Y %H:%M:%S"),' switch off all relays')
        GPIO.output(self.Relay_Ch1,GPIO.HIGH)
        GPIO.output(self.Relay_Ch2,GPIO.HIGH)
        GPIO.output(self.Relay_Ch3,GPIO.HIGH)

    def switch_on (self):
        if debug:
            print(datetime.now().strftime("%d-%m-%Y %H:%M:%S"),' switch turned on')
        GPIO.output(self.Relay_Ch3,GPIO.LOW)
    
    def switch_off(self):
        if debug:
            print(datetime.now().strftime("%d-%m-%Y %H:%M:%S"),' switch turned off')
        GPIO.output(self.Relay_Ch3,GPIO.HIGH)


class httpHandler( BaseHTTPRequestHandler ):
    def do_GET(self):
        alldevice_message = "<strong>All active Devices:</strong><br />"
        watchlist_device_message = "<strong>Active Devices in watchlist:</strong> <br />"
        try:
            self.send_response(200)
            self.send_header( 'Content-type', 'text/html' )
            self.end_headers()
            #respond active watchlist adresses
            #wfile.write has to be encoded to utf-8
            self.wfile.write ( watchlist_device_message.encode() )
            if len(s_active_wachtlist_list) > 0:
                breaksign = "<br />"
                for member in s_active_wachtlist_list:
                    self.wfile.write(
                        member.encode() + breaksign.encode()
                    )
            else:
                self.message = "No Devices connected!<br />"
                self.wfile.write( self.message.encode()
                    )
            #respond all active ip adresses
            self.wfile.write ( alldevice_message.encode() )
            if len(s_active_ip_list) > 0:
                breaksign = "<br />"
                for member in s_active_ip_list:
                    self.wfile.write(
                        member.encode() + breaksign.encode()
                    )
            else:
                self.message = "No Devices connected! <br />"
                self.wfile.write( self.message.encode()
                    )
        except IOError:
            self.send_error( 404, 'File Not Found: ')


if __name__ == '__main__':
    if debug:
        print('Pressure app starting')
    time.sleep(10.0)

    listhandler = cListHandler()
#    listhandler.check_thread_starter()

    try:
        if debug:
            print('starting HTTP Server')
        httpServer = HTTPServer( ('', 80), httpHandler )
        httpServer.serve_forever()
    except KeyboardInterrupt:
        if debug:
            print('quit request')

        listhandler.terminate()
