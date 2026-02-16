import streamlit as st
import time

#st.button("Start over")

placeholder = st.empty()

#placeholder.markdown("Hello")
#time.sleep(1)
#
#placeholder.progress(0, "Wait for it...")
#time.sleep(1)
#placeholder.progress(50, "Wait for it...")
#time.sleep(1)
#placeholder.progress(100, "Wait for it...")
#time.sleep(1)
#
#with placeholder.container():
#    st.line_chart({"data": [1, 5, 2, 6]})
#    time.sleep(1)
#    st.markdown("3...")
#    time.sleep(1)
#    st.markdown("2...")
#    time.sleep(1)
#    st.markdown("1...")
#    time.sleep(1)
#
#placeholder.markdown("Poof!")
#time.sleep(1)
#
#placeholder.empty()

st.markdown("*Streamlit* is **really** ***cool***.")
st.markdown(
    """
    :red[Streamlit] :orange[can] :green[write] :blue[text] :violet[in]
    :gray[pretty] :rainbow[colors] and :blue-background[highlight] text."""
)
st.markdown(
    "Here's a bouquet &mdash;\
            :tulip::cherry_blossom::rose::hibiscus::sunflower::blossom:"
)

multi = """If you end a line with two spaces,  
a soft return is used for the next line.

Two (or more) newline characters in a row will result in a hard return.
"""
st.markdown(multi)

if st.button("Click me!"):
    placeholder.markdown("You clicked the button!")