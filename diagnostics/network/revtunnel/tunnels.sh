#!/bin/bash

#Variables

tunnels_db=$(ssh -i /Users/kobykub/.ssh/id_ed25519_mac koby.kubecka@supportserver.cinesysinc.com "/home/koby.kubecka/bin/tunnels.sh")

ports=$(echo "$tunnels_db" | awk '{ print $1 }')


#Mapping the Ports
for port in $ports
do
	ssh -fN -L "$port":localhost:"$port" -i /Users/kobykub/.ssh/id_ed25519_mac koby.kubecka@supportserver.cinesysinc.com
echo "$port has been mapped"
done

echo ""
echo "All active tunnels have been established"
echo ""
echo "$tunnels_db"
