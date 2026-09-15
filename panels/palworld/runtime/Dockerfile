FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libc6-i386 lib32gcc-s1 lib32stdc++6 libatomic1 \
    libicu74 libpulse0 libsdl2-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/steamcmd /root/.steam/sdk64 /server \
    && curl --fail --show-error --location --retry 3 \
       https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
       | tar -xz -C /opt/steamcmd

COPY entrypoint.sh /usr/local/bin/palworld-entrypoint
RUN chmod 755 /usr/local/bin/palworld-entrypoint

ENV SteamAppId=2394010
WORKDIR /server
EXPOSE 8211/udp 8212/tcp 25575/tcp
STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/local/bin/palworld-entrypoint"]
CMD ["serve"]
