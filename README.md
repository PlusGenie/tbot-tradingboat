# tbot-tradingboat

## An Overview of TBOT: Purpose and Architecture

### The Purpose of TBOT

TBOT Is an algorithmic trading system that is designed to automate trading processes. Its purpose is to receive trade signals and execute trades using a variety of patterns and technologies. TBOT is designed to be a flexible and extensible system that can be customized to meet the needs of various trading strategies and workflows. By automating trading processes, TBOT can reduce the amount of manual work required and enable traders to focus on higher-level tasks such as strategy development and risk management.

### The Architecture of TBOT

TBOT is built using a combination of the Subscriber of the Pub/Sub pattern and the Observer pattern. It uses the Subscriber to receive messages from a Redis Stream or Pub/Sub and the Observer to deliver messages to Interactive Brokers, message applications, and the watchdog. TBOT is designed to be a flexible and extensible system that can be customized to meet the needs of various trading strategies and workflows. The architecture of TBOT enables it to be easily integrated with other systems and services, making it a powerful tool for automating trading processes.


![TBOT-on-Tradingboat-Design-pattern](https://user-images.githubusercontent.com/1986788/229383737-3149cc4e-42a5-4cf8-9d8f-f92f4444469d.png)

### TBOT on TradingBoat

TradingBoat is a platform that includes Nginx/Ngrok, Flask, Redis, TBOT, and IB Gateway.

TBOT serves as the message decoder and order placement tool, and is the brain of TradingBoat. We can refer to it as TBOT on TradingBoat.

![TBOT-on-TradingBoat](https://user-images.githubusercontent.com/1986788/226757087-16d96ad4-30f6-4310-bc70-eec3cc38dea9.png)


### TBOT Warning: For Educational Purposes Only

<code style="color : orangered">
All software provided here is intended for educational purposes only. Please be aware that any financial trading involves inherent risks and may result in financial losses. This is for educational purposes only. We strongly advise testing it solely with an Interactive Brokers Paper Account.
</code>
