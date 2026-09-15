FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gosu lib32gcc-s1 lib32stdc++6 libatomic1 libpulse0 libpulse-dev \
    libsdl2-2.0-0 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system valheim \
    && useradd --system --gid valheim --create-home --home-dir /home/valheim \
       --shell /bin/bash valheim \
    && mkdir -p /opt/steamcmd /home/valheim/.steam/sdk64 /server /saves \
    && curl --fail --show-error --location --retry 3 \
       https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
       | tar -xz -C /opt/steamcmd \
    && chown -R valheim:valheim /opt/steamcmd /home/valheim /server /saves
COPY entrypoint.sh /usr/local/bin/valheim-entrypoint
RUN chmod 755 /usr/local/bin/valheim-entrypoint
ENV SteamAppId=892970 LD_LIBRARY_PATH=/server/linux64
ENV HOME=/home/valheim USER=valheim
WORKDIR /server
EXPOSE 2456/udp 2457/udp
STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/local/bin/valheim-entrypoint"]
CMD ["serve"]
